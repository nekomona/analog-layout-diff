; Persistent Virtuoso entry points. The IPC child supervises the Python worker.
; Never wait synchronously for a worker: it may itself be waiting for CIW SKILL.
unless(boundp('ALDRuntimeIPC) ALDRuntimeIPC=nil)
; A per-CIW startup may pin its verified daemon port. RBPort can be overwritten
; by loading another bridge setup even while the original daemon is still live.
unless(boundp('ALDRuntimeBridgePort) ALDRuntimeBridgePort=nil)
unless(boundp('ALDRuntimeState) ALDRuntimeState="Stopped")
unless(boundp('ALDRuntimeLog) ALDRuntimeLog="")
unless(boundp('ALDRuntimeRestartPending) ALDRuntimeRestartPending=nil)
unless(boundp('ALDRuntimeKnownSources) ALDRuntimeKnownSources=nil)
unless(boundp('ALDRuntimeWorkerPid) ALDRuntimeWorkerPid=0)
unless(boundp('ALDRuntimeBeat) ALDRuntimeBeat="None")
unless(boundp('ALDRuntimeLastActivity) ALDRuntimeLastActivity="Idle")
when(boundp('ALDRuntimeForm) && ALDRuntimeForm
  hiFormCancel(ALDRuntimeForm) hiDeleteForm(ALDRuntimeForm) ALDRuntimeForm=nil)

when(boundp('ALDGUIActionsForm) && ALDGUIActionsForm
  hiFormCancel(ALDGUIActionsForm) hiDeleteForm(ALDGUIActionsForm) ALDGUIActionsForm=nil)

procedure(ALDRuntimeActivity(text)
  ALDRuntimeLastActivity=text ALDRuntimeUpdate())

procedure(ALDRuntimeLogs()
  let((port line text)
    text="" port=infile(strcat(ALDRuntimeRoot "/runtime.log"))
    when(port
      unwindProtect(
        while(gets(line port)
          text=strcat(text line)
          when(strlen(text)>16000 text=substring(text strlen(text)-11999)))
        close(port)))
    when(text=="" text="No worker errors or diagnostic output recorded.")
    ALDGUINotice(text)))

procedure(ALDRuntimeUpdate()
  when(boundp('ALDRuntimeForm) && ALDRuntimeForm
    ALDRuntimeForm->aldMonitor->value=sprintf(nil
      "State: %s\nWorker PID: %d   Virtuoso PID: %d\nLast response: %s\nQueued operations: %d\nWorkspace: %s\nActivity: %s\n\n%s"
      ALDRuntimeState ALDRuntimeWorkerPid ipcGetPid() ALDRuntimeBeat
      length(ALDGUIQueue) ALDRuntimeRoot ALDRuntimeLastActivity ALDRuntimeLog)))

procedure(ALDRuntimeData(cid data)
  when(cid==ALDRuntimeIPC
    ALDRuntimeLog=strcat(ALDRuntimeLog data)
    when(strlen(ALDRuntimeLog)>10000
      ALDRuntimeLog=substring(ALDRuntimeLog strlen(ALDRuntimeLog)-7999))
    printf("Layout Diff runtime: %s" data)
    ALDRuntimeUpdate()))

procedure(ALDRuntimeExited(cid status)
  when(cid==ALDRuntimeIPC
    ALDRuntimeIPC=nil ALDRuntimeWorkerPid=0
    when(ALDGUIOwner ALDGUIStop(ALDGUIOwner))
    ALDRuntimeState=sprintf(nil "Stopped (exit %d)" status)
    ALDRuntimeUpdate()
    when(ALDRuntimeRestartPending
      ALDRuntimeRestartPending=nil
      hiRegTimer("ALDRuntimeStart()" 1))))

procedure(ALDRuntimeStart()
  if(ALDRuntimeIPC then
    ALDRuntimePanel()
  else
    ALDRuntimeState="Starting" ALDRuntimeLog="" ALDRuntimeWorkerPid=0
    ALDRuntimeIPC=ipcBeginProcess(
      sprintf(nil "%s --parent %d --port %d" ALDRuntimeCommand ipcGetPid()
        if(ALDRuntimeBridgePort then ALDRuntimeBridgePort else RBPort))
      "" 'ALDRuntimeData 'ALDRuntimeData 'ALDRuntimeExited)
    unless(ALDRuntimeIPC ALDRuntimeState="Failed to launch")
    ALDRuntimeUpdate()) t)

procedure(ALDRuntimeStop()
  ALDRuntimeRestartPending=nil
  when(ALDRuntimeIPC
    ALDRuntimeState="Stopping (current operation may finish)"
    ipcWriteProcess(ALDRuntimeIPC "STOP\n")
    ALDRuntimeUpdate()) t)

procedure(ALDRuntimeRestart()
  if(ALDRuntimeIPC then
    ALDRuntimeStop() ALDRuntimeRestartPending=t
  else ALDRuntimeStart()) t)

procedure(ALDRuntimeExit()
  ; regExitAfter runs only after Virtuoso has accepted exit; it never vetoes it.
  ALDRuntimeRestartPending=nil
  when(boundp('ALDGUILeases) errset(ALDGUILeaseExit() t))
  when(ALDRuntimeIPC errset(ipcWriteProcess(ALDRuntimeIPC "STOP\n") nil)) t)

procedure(ALDRuntimeReady(owner pid root)
  when(ALDGUIOwner==owner
    ALDRuntimeWorkerPid=pid ALDRuntimeRoot=root ALDRuntimeState="Running"
    ALDRuntimeBeat=getCurrentTime() ALDRuntimeUpdate()))

procedure(ALDRuntimeHeartbeat(pid count)
  ALDRuntimeWorkerPid=pid ALDRuntimeBeat=getCurrentTime()
  unless(ALDRuntimeState=="Stopping (current operation may finish)" ALDRuntimeState="Running")
  ALDRuntimeUpdate() t)

procedure(ALDRuntimeSources(identities)
  ALDRuntimeKnownSources=identities
  when(boundp('ALDGUIActionsForm) && ALDGUIActionsForm
    ALDGUIActionsForm->aldSources->choices=foreach(mapcar identity identities
      sprintf(nil "%s / %s / %s" car(identity) cadr(identity) caddr(identity)))) t)

procedure(ALDRuntimePickSource(form)
  let((index identity)
    index=car(form->aldSources->value)
    when(index
      identity=nth(index-1 ALDRuntimeKnownSources)
      form->aldLib->value=car(identity) form->aldCell->value=cadr(identity)
      form->aldView->value=caddr(identity))))

procedure(ALDRuntimeRequest(command)
  let((f identity)
    f=ALDGUIActionsForm
    identity=list(f->aldLib->value f->aldCell->value f->aldView->value)
    if(member("" identity) then ALDGUINotice("Choose a library, cell and layout view first.")
    else
      if(command=="commit" then
        ALDGUIQuickSaveIdentity(identity)
      else ALDGUIEnqueue(append(list(command) identity))))))

procedure(ALDGUIActionsPanel()
  let((lib cell view sources)
    unless(boundp('ALDGUIActionsForm) && ALDGUIActionsForm
      lib=hiCreateStringField(?name 'aldLib ?prompt "Library" ?value "")
      cell=hiCreateStringField(?name 'aldCell ?prompt "Cell" ?value "")
      view=hiCreateStringField(?name 'aldView ?prompt "View" ?value "layout")
      sources=hiCreateListBoxField(?name 'aldSources ?prompt "Recorded layouts" ?choices nil
        ?multipleSelect nil ?valueByPosition t ?numRows 5 ?callback "ALDRuntimePickSource(ALDGUIActionsForm)")
      ALDGUIActionsForm=hiCreateAppForm(?name 'ALDGUIActionsForm ?formTitle "Layout Diff - Layout actions"
        ?fields list(list(sources 10:10 760:140 130)
          list(lib 10:160 760:30 130) list(cell 10:200 760:30 130) list(view 10:240 760:30 130)
          list(hiCreateButton(?name 'aldCommit ?buttonText "Save && Commit" ?callback "ALDRuntimeRequest(\"commit\")") 10:290 230:30)
          list(hiCreateButton(?name 'aldHistory ?buttonText "History && Changes" ?callback "ALDRuntimeRequest(\"history\")") 260:290 250:30)
          list(hiCreateButton(?name 'aldMerge ?buttonText "Merge / resolve conflicts" ?callback "ALDGUIEnqueue(list(\"merge-setup\"))") 530:290 240:30)
          list(hiCreateButton(?name 'aldRefresh ?buttonText "Refresh layouts" ?callback "ALDGUIEnqueue(list(\"sources\"))") 10:335 230:30))
        ?initialSize list(800 430) ?buttonLayout 'Close ?dontBlock t ?dialogStyle 'modeless))
    ALDRuntimeSources(ALDRuntimeKnownSources)
    hiDisplayForm(ALDGUIActionsForm)))

procedure(ALDRuntimePanel()
  unless(boundp('ALDRuntimeForm) && ALDRuntimeForm
    ALDRuntimeForm=hiCreateAppForm(?name 'ALDRuntimeForm ?formTitle "Layout Diff - Diagnostics and background service"
      ?fields list(list(hiCreateMLTextField(?name 'aldMonitor ?prompt "" ?editable nil ?enableWordWrap t) 10:10 760:260)
        list(hiCreateButton(?name 'aldStart ?buttonText "Start" ?callback "ALDRuntimeStart()") 10:280 100:30)
        list(hiCreateButton(?name 'aldStop ?buttonText "Stop" ?callback "ALDRuntimeStop()") 120:280 100:30)
        list(hiCreateButton(?name 'aldRestart ?buttonText "Restart" ?callback "ALDRuntimeRestart()") 230:280 100:30)
        list(hiCreateButton(?name 'aldLogs ?buttonText "Worker log" ?callback "ALDRuntimeLogs()") 340:280 180:30)
        list(hiCreateButton(?name 'aldClean ?buttonText "Clean closed reviews" ?callback "ALDGUIEnqueue(list(\"cleanup\"))") 530:280 240:30)
        list(hiCreateButton(?name 'aldPerformance ?buttonText "Performance backend..." ?callback "ALDGUIEnqueue(list(\"backend-info\"))") 10:325 760:30))
      ?initialSize list(800 420) ?buttonLayout 'Close ?dontBlock t ?dialogStyle 'modeless))
  ALDRuntimeUpdate() hiDisplayForm(ALDRuntimeForm))

procedure(ALDRuntimeInstall()
  let((n)
    ; Replace the old menu in place on reload, including pre-separation versions.
    n=0
    foreach(menu hiGetBannerMenus(hiGetCIWindow())
      when(menu=='ALDRuntimeMenu hiDeleteBannerMenu(hiGetCIWindow() n))
      n=n+1)
    ALDRuntimeMenu=hiCreatePulldownMenu('ALDRuntimeMenu "Layout Diff"
      list(
        hiCreateMenuItem(?name 'aldCommit ?itemText "Save && Commit / Select layout..." ?callback "ALDGUIActionsPanel()")
        hiCreateMenuItem(?name 'aldBrowser ?itemText "History && Changes..." ?callback "ALDGUIBrowser()")
        hiCreateMenuItem(?name 'aldMerge ?itemText "Merge / Resolve active conflicts..." ?callback "ALDGUIEnqueue(list(\"merge-setup\"))")
        hiCreateSeparatorMenuItem(?name 'aldDiagnosticsSeparator)
        hiCreateMenuItem(?name 'aldPanel ?itemText "Diagnostics / Background service..." ?callback "ALDRuntimePanel()")
        hiCreateMenuItem(?name 'aldLogs ?itemText "Worker log..." ?callback "ALDRuntimeLogs()")
        hiCreateMenuItem(?name 'aldPerformance ?itemText "Performance backend..." ?callback "ALDGUIEnqueue(list(\"backend-info\"))")
        hiCreateMenuItem(?name 'aldStart ?itemText "Start service" ?callback "ALDRuntimeStart()")
        hiCreateMenuItem(?name 'aldStop ?itemText "Stop service" ?callback "ALDRuntimeStop()")
        hiCreateMenuItem(?name 'aldRestart ?itemText "Restart service" ?callback "ALDRuntimeRestart()")))
    hiInsertBannerMenu(hiGetCIWindow() ALDRuntimeMenu hiGetNumMenus(hiGetCIWindow())))
  unless(boundp('ALDRuntimeExitRegistered)
    regExitAfter('ALDRuntimeExit) ALDRuntimeExitRegistered=t)
  t)
