; Agent requests are data. Never evaluate payloads or wait for the Python worker.
; ALDAgentRoot is installed by the owning worker after creating its directories.
procedure(ALDAgentRead(path)
  let((port line text)
    port=infile(path)
    when(port
      text=""
      unwindProtect(while(gets(line port) text=strcat(text line)) close(port))
      text)))

procedure(ALDAgentID(id)
  unless(stringp(id) && strlen(id)>0 && strlen(id)<=64 &&
      rexMatchp("^[A-Za-z0-9_-][A-Za-z0-9_-]*$" id)
    error("Invalid Layout Diff agent request ID")) id)

procedure(ALDAgentDescribe()
  unless(boundp('ALDAgentRoot) error("Start the updated Layout Diff runtime first"))
  list("layoutdiff-agent/1" if(boundp('ALDGUIOwner) && ALDGUIOwner then t else nil)
    ALDAgentRead(strcat(ALDAgentRoot "/capabilities.json"))))

procedure(ALDAgentSubmit(id operation payload)
  let((path text old port temp)
    ALDAgentID(id)
    unless(boundp('ALDAgentRoot) && boundp('ALDGUIOwner) && ALDGUIOwner
      error("Start the updated Layout Diff runtime first"))
    unless(member(operation '("diff" "merge_plan" "merge_explain" "merge_apply" "export"))
      error("Unknown Layout Diff agent operation"))
    unless(stringp(payload) && strlen(payload)<=48000 error("Agent payload exceeds 48000 bytes"))
    path=strcat(ALDAgentRoot "/requests/" id ".request")
    text=strcat(operation "\n" payload) old=ALDAgentRead(path)
    if(old then
      unless(old==text error("Request ID already has a different payload"))
      list("existing" id)
    else
      temp=strcat(path ".tmp") port=outfile(temp)
      unless(port error("Cannot write agent request"))
      unwindProtect(fprintf(port "%s" text) close(port))
      unless(renameFile(temp path) error("Cannot publish agent request"))
      list("accepted" id))))

procedure(ALDAgentResult(id @optional (cursor 0))
  let((prefix count chunk)
    ALDAgentID(id)
    unless(boundp('ALDAgentRoot) error("Load the updated Layout Diff runtime first"))
    unless(fixp(cursor) && cursor>=0 error("Invalid agent result cursor"))
    prefix=strcat(ALDAgentRoot "/requests/" id)
    count=ALDAgentRead(strcat(prefix ".done"))
    cond(
      (count
        count=atoi(count)
        unless(cursor<count error("Agent result cursor is out of range"))
        chunk=ALDAgentRead(sprintf(nil "%s.page.%d" prefix cursor))
        unless(chunk error("Agent result page is missing"))
        list("complete" count chunk))
      (ALDAgentRead(strcat(prefix ".running")) list("running" id))
      (ALDAgentRead(strcat(prefix ".request")) list("pending" id))
      (t list("not_found" id)))))

procedure(ALDAgentSourceState(lib cell view)
  let((cv)
    cv=dbOpenCellViewByType(lib cell view "maskLayout" "r")
    unless(cv error("Source layout is unavailable"))
    unwindProtect(list(dbIsCellViewModified(cv) cv~>modifiedCounter) dbClose(cv))))

procedure(ALDAgentSave(lib cell view)
  let((cv)
    unless(ddGetObj(lib cell view) error("Source layout does not exist"))
    cv=dbOpenCellViewByType(lib cell view "maskLayout" "a")
    unless(cv error("Cannot open the selected layout for saving"))
    unwindProtect(
      progn(unless(dbSave(cv) error("Cannot save the selected layout")) t)
      dbClose(cv))))
