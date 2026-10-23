// Streaming acceleration only. Python storage.py owns schema and semantic checks.
// Canonical JSON numbers/records are opaque bytes: no floating-point conversions.
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {
constexpr std::size_t max_line = 64 * 1024 * 1024;

class Lines {
    std::ifstream input;
    std::array<char, 65536> buffer{};
    std::size_t position = 0, available = 0;
public:
    explicit Lines(const char* path) : input(path, std::ios::binary) {
        if (!input) throw std::runtime_error("Cannot open input");
    }
    bool next(std::string& line) {
        line.clear();
        for (;;) {
            if (position == available) {
                input.read(buffer.data(), buffer.size());
                available = static_cast<std::size_t>(input.gcount()); position = 0;
                if (input.bad()) throw std::runtime_error("Input read failed");
                if (!available) {
                    if (!line.empty()) throw std::runtime_error("Unterminated input line");
                    return false;
                }
            }
            const auto* begin = buffer.data() + position;
            const auto* end = static_cast<const char*>(std::memchr(begin, '\n', available - position));
            const auto length = end ? static_cast<std::size_t>(end - begin) : available - position;
            if (line.size() + length > max_line) throw std::runtime_error("Oversize input line");
            line.append(begin, length); position += length;
            if (end) { ++position; return true; }
        }
    }
};

unsigned nibble(char c) {
    if (c >= '0' && c <= '9') return static_cast<unsigned>(c - '0');
    if (c >= 'a' && c <= 'f') return static_cast<unsigned>(c - 'a' + 10);
    throw std::runtime_error("Invalid hex key");
}

void validate_key(std::string_view key) {
    if (key.empty() || key.size() % 2) throw std::runtime_error("Invalid key length");
    for (char c : key) (void)nibble(c);
}

std::string quoted_key(std::string_view key) {
    std::string bytes;
    bytes.reserve(key.size() / 2);
    for (std::size_t i = 0; i < key.size(); i += 2)
        bytes.push_back(static_cast<char>((nibble(key[i]) << 4) | nibble(key[i + 1])));
    std::string result = "\"";
    const char* hex = "0123456789abcdef";
    auto escape = [&](std::uint32_t cp) {
        result += "\\u";
        for (int shift = 12; shift >= 0; shift -= 4) result += hex[(cp >> shift) & 15];
    };
    for (std::size_t i = 0; i < bytes.size();) {
        auto c = static_cast<unsigned char>(bytes[i++]);
        std::uint32_t cp = c;
        if (c >= 128) {
            unsigned n;
            std::uint32_t minimum;
            if (c >= 0xc2 && c <= 0xdf) { n = 1; cp = c & 31; minimum = 0x80; }
            else if (c >= 0xe0 && c <= 0xef) { n = 2; cp = c & 15; minimum = 0x800; }
            else if (c >= 0xf0 && c <= 0xf4) { n = 3; cp = c & 7; minimum = 0x10000; }
            else throw std::runtime_error("Invalid UTF-8 key");
            if (i + n > bytes.size()) throw std::runtime_error("Truncated UTF-8 key");
            for (unsigned j = 0; j < n; ++j) {
                auto next = static_cast<unsigned char>(bytes[i++]);
                if ((next & 0xc0) != 0x80) throw std::runtime_error("Invalid UTF-8 continuation");
                cp = (cp << 6) | (next & 63);
            }
            if (cp < minimum || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff))
                throw std::runtime_error("Invalid Unicode scalar");
        }
        switch (cp) {
            case '"': result += "\\\""; break;
            case '\\': result += "\\\\"; break;
            case '\b': result += "\\b"; break;
            case '\f': result += "\\f"; break;
            case '\n': result += "\\n"; break;
            case '\r': result += "\\r"; break;
            case '\t': result += "\\t"; break;
            default:
                if (cp >= 32 && cp < 127) result += static_cast<char>(cp);
                else if (cp <= 0xffff) escape(cp);
                else { cp -= 0x10000; escape(0xd800 + (cp >> 10)); escape(0xdc00 + (cp & 1023)); }
        }
    }
    return result + '"';
}

struct Rows {
    Lines input;
    std::string line, key, value, previous;
    bool present = false;
    explicit Rows(const char* path) : input(path) { advance(); }
    void advance() {
        present = input.next(line);
        if (!present) return;
        auto separator = line.find('\t');
        if (separator == std::string::npos) throw std::runtime_error("Invalid wire row");
        key = line.substr(0, separator); validate_key(key);
        if (key <= previous) throw std::runtime_error("Duplicate or unsorted wire key");
        previous = key; value = line.substr(separator + 1);
        if (value.empty() || value.front() != '{' || value.back() != '}' || value.find('\t') != std::string::npos)
            throw std::runtime_error("Invalid wire record envelope");
    }
};

void emit(std::ostream& out, const std::string& key, const std::string& before, const std::string& after) {
    out << "{\"after\":" << after << ",\"before\":" << before << ",\"key\":" << quoted_key(key) << "}\n";
}

void diff(const char* before, const char* after, const char* output) {
    Rows a(before), b(after);
    std::ofstream out(output, std::ios::binary);
    if (!out) throw std::runtime_error("Cannot open output");
    while (a.present || b.present) {
        if (!b.present || (a.present && a.key < b.key)) { emit(out, a.key, a.value, "null"); a.advance(); }
        else if (!a.present || b.key < a.key) { emit(out, b.key, "null", b.value); b.advance(); }
        else {
            if (a.value != b.value) emit(out, a.key, a.value, b.value);
            a.advance(); b.advance();
        }
    }
    out.flush();
    if (!out) throw std::runtime_error("Output write failed");
}

struct Changes {
    Lines input;
    std::string line, key, before, after, previous;
    bool present = false;
    explicit Changes(const char* path) : input(path) { advance(); }
    void advance() {
        present = input.next(line);
        if (!present) return;
        auto p = line.find('\t'), q = p == std::string::npos ? p : line.find('\t', p + 1);
        if (q == std::string::npos || line.find('\t', q + 1) != std::string::npos)
            throw std::runtime_error("Invalid wire patch");
        key = line.substr(0, p); validate_key(key);
        if (key <= previous) throw std::runtime_error("Duplicate or unsorted patch key");
        previous = key; before = line.substr(p + 1, q - p - 1); after = line.substr(q + 1);
        auto valid = [](const std::string& value) { return value == "null" || (value.size() >= 2 && value.front() == '{' && value.back() == '}'); };
        if (!valid(before) || !valid(after) || (before == "null" && after == "null"))
            throw std::runtime_error("Invalid wire patch values");
    }
};

void apply(const char* source, const char* patch, const char* output) {
    Rows a(source); Changes b(patch);
    std::ofstream out(output, std::ios::binary);
    if (!out) throw std::runtime_error("Cannot open output");
    while (a.present || b.present) {
        if (!b.present || (a.present && a.key < b.key)) { out << a.key << '\t' << a.value << '\n'; a.advance(); }
        else {
            const bool matches = a.present && a.key == b.key;
            if ((matches ? a.value : "null") != b.before) throw std::runtime_error("Object precondition mismatch");
            if (b.after != "null") out << b.key << '\t' << b.after << '\n';
            if (matches) a.advance();
            b.advance();
        }
    }
    out.flush();
    if (!out) throw std::runtime_error("Output write failed");
}
}

int main(int argc, char** argv) {
    try {
        if (argc == 2 && std::string(argv[1]) == "--version") {
            std::cout << "layoutdiff-native/1 wire/1 diff apply\n"; return 0;
        }
        if (argc != 5) throw std::runtime_error("Usage: layoutdiff-native diff|apply INPUT1 INPUT2 OUTPUT");
        if (std::string(argv[2]) == argv[4] || std::string(argv[3]) == argv[4])
            throw std::runtime_error("Output must differ from inputs");
        const std::string command(argv[1]);
        if (command == "diff") diff(argv[2], argv[3], argv[4]);
        else if (command == "apply") apply(argv[2], argv[3], argv[4]);
        else throw std::runtime_error("Unknown command");
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 2;
    }
}
