; Window leases survive worker restarts. The timer never calls the bridge.
unless(boundp('ALDGUILeases) ALDGUILeases=makeTable('aldLeases nil))
unless(boundp('ALDGUILeaseTimer) ALDGUILeaseTimer=nil)
unless(boundp('ALDGUIActiveLease) ALDGUIActiveLease=nil)
unless(boundp('ALDGUIBusyActive) ALDGUIBusyActive=nil)
unless(boundp('ALDGUIBusyText) ALDGUIBusyText=nil)

procedure(ALDGUILeaseBegin(token path)
  let((state)
    state=makeTable('aldLease nil) state['path]=path
    ALDGUILeases[token]=state ALDGUIActiveLease=token))

procedure(ALDGUILeaseLibrary(token lib)
  ALDGUILeases[token]['libraries]=cons(lib ALDGUILeases[token]['libraries]))

procedure(ALDGUILeaseWatchReview(reviewToken)
  let((cv)
    cv=ALDGUIHeld[reviewToken]
    when(ALDGUIActiveLease && cv
      ALDGUILeases[ALDGUIActiveLease]['watchLibraries]=list(cv~>libName))))

procedure(ALDGUILeaseForm(form)
  when(ALDGUIActiveLease
    form->aldLease=ALDGUIActiveLease
    ALDGUILeases[ALDGUIActiveLease]['forms]=cons(form ALDGUILeases[ALDGUIActiveLease]['forms])))

procedure(ALDGUIViewFile(path title)
  let((win)
    win=hiViewTextFile(path ?title title ?fixedFont t)
    when(ALDGUIActiveLease && win
      ALDGUILeases[ALDGUIActiveLease]['windows]=cons(win ALDGUILeases[ALDGUIActiveLease]['windows]))
    win))

procedure(ALDGUILeaseSeal(token)
  when(ALDGUILeases[token] ALDGUILeases[token]['sealed]=t)
  ALDGUIActiveLease=nil
  unless(ALDGUILeaseTimer ALDGUILeaseTimer=t hiRegTimer("ALDGUILeaseTick()" 10)))

procedure(ALDGUILeaseTick()
  let((live state libs busy cv dd port pending shown)
    ALDGUILeaseTimer=nil live=hiGetWindowList()
    foreach(token ALDGUILeases
      state=ALDGUILeases[token]
      when(state && state['sealed]
        libs=append(state['libraries] state['watchLibraries]) busy=or(state['hold] state['recovery])
        foreach(win live
          when(member(win state['windows]) busy=t)
          foreach(cv list(win->cellView win->editCellView win->displayCellView)
            when(cv && (member(cv~>libName libs) ||
              member(list(cv~>libName cv~>cellName cv~>viewName) state['watchCells])) busy=t)))
        foreach(form state['forms]
          shown=errset(form->aldLease==token && hiIsFormDisplayed(form) nil)
          when(car(shown) busy=t))
        unless(busy
          ; Balance our own held opens only after every GUI reference is gone.
          foreach(reviewToken ALDGUIHeld
            cv=ALDGUIHeld[reviewToken]
            when(cv && member(cv~>libName state['libraries])
              ALDGUIDiscard(reviewToken) ALDGUIStyleData[reviewToken]=nil ALDGUIReviews[reviewToken]=nil))
          foreach(cv dbGetOpenCellViews() when(member(cv~>libName libs) busy=t)))
        unless(busy
          foreach(lib state['libraries]
            dd=ddGetObj(lib)
            when(dd
              ; A lease may only delete the library created in its own bundle.
              if(dd~>readPath==strcat(state['path] "/oa") then
                ddDeleteObj(dd) when(ddGetObj(lib) busy=t)
              else busy=t)))
          unless(busy
            port=outfile(strcat(state['path] "/RELEASED"))
            when(port fprintf(port "released\n") close(port) ALDGUILeases[token]=nil))))
      when(ALDGUILeases[token] pending=t))
    when(pending ALDGUILeaseTimer=t hiRegTimer("ALDGUILeaseTick()" 10)) t))

procedure(ALDGUIBrowserSetStatus(form text)
  form->aldIdleStatus=text
  form->aldBrowserStatus->value=if(ALDGUIBusyActive then strcat("Loading: " ALDGUIBusyText) else text))

procedure(ALDGUIBusyUpdate(text)
  when(ALDGUIBusyActive
    ALDGUIBusyText=text
    when(boundp('ALDGUIHistoryForm) && ALDGUIHistoryForm
      ALDGUIHistoryForm->aldBrowserStatus->value=strcat("Loading: " text))
    when(boundp('ALDGUIBusyForm) && ALDGUIBusyForm ALDGUIBusyForm->aldBusyText->value=text)))

procedure(ALDGUIBusyStart(text @optional (popup nil))
  ALDGUIBusyActive=t
  ALDGUIBusyUpdate(text)
  if(popup then
    unless(boundp('ALDGUIBusyForm) && ALDGUIBusyForm
    ALDGUIBusyForm=hiCreateLayoutForm('ALDGUIBusyForm "Layout Diff - Loading"
      hiCreateVerticalBoxLayout('aldBusyLayout ?margins '(16 16 16 16) ?items list(
        hiCreateStringField(?name 'aldBusyText ?prompt "" ?editable nil)
        hiCreateLabel(?name 'aldBusyHint ?labelText "Working... You can hide this window; the operation will continue.")))
      ?initialSize '(650 150) ?buttonLayout 'Close ?dialogStyle 'modeless))
    ALDGUIBusyForm->aldBusyText->value=text hiDisplayForm(ALDGUIBusyForm)
  else
    when(boundp('ALDGUIBusyForm) && ALDGUIBusyForm hiFormCancel(ALDGUIBusyForm))))

procedure(ALDGUIBusyDone()
  ALDGUIBusyActive=nil ALDGUIBusyText=nil
  when(boundp('ALDGUIBusyForm) && ALDGUIBusyForm hiFormCancel(ALDGUIBusyForm))
  when(boundp('ALDGUIHistoryForm) && ALDGUIHistoryForm
    ALDGUIHistoryForm->aldBrowserStatus->value=or(ALDGUIHistoryForm->aldIdleStatus "Ready")))

procedure(ALDGUIRestoreConfirm(token text)
  unless(boundp('ALDGUIRestoreForm) && ALDGUIRestoreForm
    ALDGUIRestoreForm=hiCreateLayoutForm('ALDGUIRestoreForm "Layout Diff - Restore checkpoint"
      hiCreateVerticalBoxLayout('aldRestoreLayout ?margins '(12 12 12 12) ?items list(
        hiCreateMLTextField(?name 'aldRestoreText ?prompt "" ?editable nil ?enableWordWrap t)))
      ?initialSize '(760 370) ?buttonLayout 'OKCancel
      ?callback list('ALDGUIRestoreOK 'ALDGUIRestoreCancel) ?dialogStyle 'modeless))
  ALDGUIRestoreForm->aldToken=token ALDGUIRestoreForm->aldRestoreText->value=text
  hiDisplayForm(ALDGUIRestoreForm))

procedure(ALDGUIRestoreOK(form)
  when(form->aldToken ALDGUIEnqueue(list("restore-apply" form->aldToken)) form->aldToken=nil))
procedure(ALDGUIRestoreCancel(form)
  when(form->aldToken ALDGUIEnqueue(list("restore-cancel" form->aldToken)) form->aldToken=nil))

procedure(ALDGUIRestoreMatches(cv identity)
  cv && list(cv~>libName cv~>cellName cv~>viewName)==identity)

procedure(ALDGUILeaseExit()
  ; Called only after Virtuoso accepts exit. Purge only owned temporary OA data;
  ; never a source layout. This also removes native library-list definitions.
  let((state dd port)
    foreach(token ALDGUILeases
      state=ALDGUILeases[token]
      when(state
        foreach(lib state['libraries]
          dd=ddGetObj(lib)
          when(dd && dd~>readPath==strcat(state['path] "/oa")
            foreach(cv dbGetOpenCellViews() when(cv~>libName==lib dbPurge(cv)))
            ddDeleteObj(dd)))
        port=outfile(strcat(state['path] "/RELEASED"))
        when(port fprintf(port "parent exit\n") close(port)))) t))

procedure(ALDGUIRestoreOpen(identity modes)
  foreach(mode or(modes list("a"))
    unless(deOpenCellView(car(identity) cadr(identity) caddr(identity) "maskLayout" nil mode)
      error("Cannot reopen restored layout"))) t)

procedure(ALDGUIRestoreBackup(identity backupLib)
  let((cv backup windows modes)
    cv=dbOpenCellViewByType(car(identity) cadr(identity) caddr(identity) "maskLayout" "r")
    unless(cv error("Target layout is unavailable"))
    unwindProtect(
      progn(
        when(dbIsCellViewModified(cv) error("Save or discard target edits before restore"))
        foreach(win hiGetWindowList()
          when(ALDGUIRestoreMatches(win->editCellView identity) && !ALDGUIRestoreMatches(win->displayCellView identity)
            error("Exit edit-in-place before restoring this layout"))
          when(ALDGUIRestoreMatches(win->displayCellView identity)
            windows=cons(win windows) modes=cons(cv~>mode modes)))
        backup=dbCopyCellView(cv backupLib "backup" "layout")
        unless(backup error("Cannot create native restore backup"))
        dbClose(backup))
      dbClose(cv))
    foreach(win windows hiCloseWindow(win))
    when(setof(openCV dbGetOpenCellViews() ALDGUIRestoreMatches(openCV identity))
      when(modes ALDGUIRestoreOpen(identity modes))
      error("Target is still referenced by another database/editor. Close dependent layouts before restore"))
    or(modes list("a"))))

procedure(ALDGUIRestoreCopy(lib cell identity)
  let((source result)
    when(setof(cv dbGetOpenCellViews() ALDGUIRestoreMatches(cv identity))
      error("Target is open; replacement refused"))
    source=dbOpenCellViewByType(lib cell "layout" "maskLayout" "r")
    unless(source error("Restore source unavailable"))
    unwindProtect(
      progn(result=dbCopyCellView(source car(identity) cadr(identity) caddr(identity) nil nil t)
        unless(result error("Native checkpoint copy failed"))
        unwindProtect(unless(dbSave(result) error("Restored layout save failed")) dbClose(result)))
      dbClose(source)) t))
