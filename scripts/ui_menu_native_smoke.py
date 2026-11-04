"""Verify native action/diagnostics separation and idempotent menu upgrades."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from virtuoso_bridge import SSHClient,VirtuosoClient
from layoutdiff.eda.virtuoso.adapter import checked
from layoutdiff.eda.virtuoso.sexpr import loads


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile')
    args=parser.parse_args()
    tunnel=SSHClient.from_env(profile=args.profile); tunnel.warm()
    client=VirtuosoClient.from_tunnel(tunnel)
    root=Path(__file__).resolve().parents[1]
    def call(expression):
        result=client.execute_skill('progn(' + expression + ')')
        if result.warnings: raise RuntimeError(result.warnings)
        return checked(result)
    menus=[m['symbol'] for m in loads(call('hiGetBannerMenus(hiGetCIWindow())'))]
    checked(client.load_il(root/'layoutdiff/ui/skill/runtime.il'))
    for _ in range(2):
        call('ALDRuntimeInstall()')
        after=[m['symbol'] for m in loads(call('hiGetBannerMenus(hiGetCIWindow())'))]
        assert [m for m in menus if m!='ALDRuntimeMenu']==[m for m in after if m!='ALDRuntimeMenu']
        assert after.count('ALDRuntimeMenu')==1
    items=[m['symbol'] for m in loads(call('hiGetMenuItems(ALDRuntimeMenu)'))]
    assert items==['aldCommit','aldBrowser','aldMerge','aldDiagnosticsSeparator','aldPanel','aldLogs','aldPerformance','aldStart','aldStop','aldRestart'],items
    try:
        call('ALDGUIActionsPanel()')
        call('ALDRuntimePanel()')
        assert loads(call('list(when(ALDGUIActionsForm->aldCommit t) when(ALDGUIActionsForm->aldMerge t) ALDGUIActionsForm->aldMonitor ALDRuntimeForm->aldCommit ALDRuntimeForm->aldSources when(ALDRuntimeForm->aldMonitor t))'))==[True,True,None,None,None,True]
    finally:
        call('hiFormCancel(ALDGUIActionsForm) hiFormCancel(ALDRuntimeForm)')
    print('PASS: menu upgrade is idempotent; commit/history/merge above separator; separate action and diagnostics forms')


if __name__=='__main__':main()
