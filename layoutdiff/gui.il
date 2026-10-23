; Analog Layout Diff UI. Callbacks enqueue data; the Python bridge worker performs IO.
; All forms are modeless/nonblocking. Only explicit Save & Commit saves a source.
unless(boundp('ALDGUIOwner) ALDGUIOwner=nil)
unless(boundp('ALDGUIQueue) ALDGUIQueue=nil)
unless(boundp('ALDGUIWindows) ALDGUIWindows=makeTable('aldGuiWindows nil))
unless(boundp('ALDGUIObjects) ALDGUIObjects=makeTable('aldGuiObjects nil))
unless(boundp('ALDGUIHeld) ALDGUIHeld=makeTable('aldGuiHeld nil))
unless(boundp('ALDGUIReviews) ALDGUIReviews=makeTable('aldGuiReviews nil))
unless(boundp('ALDGUIStyleData) ALDGUIStyleData=makeTable('aldGuiStyles nil))
unless(boundp('ALDGUIKnownWindows) ALDGUIKnownWindows=nil)
unless(boundp('ALDGUIQuickKey) ALDGUIQuickKey=nil)
unless(boundp('ALDGUIShadowData) ALDGUIShadowData=makeTable('aldShadows nil))
unless(boundp('ALDGUIBlinkGeneration) ALDGUIBlinkGeneration=0)
; Invalidate already queued one-shot timers on reload, without resetting IDs.
ALDGUIBlinkGeneration=ALDGUIBlinkGeneration+1
ALDGUIBlinkScheduled=nil
ALDGUIBlinkPhase=t
ALDGUIStyleChoices='(("Untouched" "untouched") ("Modified" "changed") ("Modified net" "netChanged")
  ("New" "new") ("Deleted" "deleted") ("New groups" "groupNew") ("Modified groups" "groupChanged") ("Deleted groups" "groupDeleted"))
ALDGUIHighlightGroups=foreach(mapcar choice ALDGUIStyleChoices cadr(choice))
; Recreate the preview after a plugin reload so upgraded field layouts take effect.
when(boundp('ALDGUIQuickForm) && ALDGUIQuickForm
  hiFormCancel(ALDGUIQuickForm) hiDeleteForm(ALDGUIQuickForm))
when(boundp('ALDGUIResultForm) && ALDGUIResultForm
  hiFormCancel(ALDGUIResultForm) hiDeleteForm(ALDGUIResultForm) ALDGUIResultForm=nil)
when(boundp('ALDGUIStyleForm) && ALDGUIStyleForm
  hiFormCancel(ALDGUIStyleForm) hiDeleteForm(ALDGUIStyleForm) ALDGUIStyleForm=nil)

procedure(ALDGUIInstallQuickKey()
  let((key binding)
    unless(ALDGUIQuickKey
      foreach(candidate '("Shift Ctrl<Key>s" "Shift Ctrl<Key>g" "Shift Ctrl<Key>F12")
        unless(key
          binding=hiGetBindKey("Layout" candidate)
          when(!binding || binding=="" key=candidate)))
      when(key
        ALDGUIQuickKey=key
        hiSetBindKey("Layout" key "ALDGUIQuickSave(hiGetCurrentWindow())")
        printf("Layout Diff Save & Commit shortcut: %s\n" key))) t))

procedure(ALDGUIRequireSaved(identity)
  let((cv result)
    cv=dbOpenCellViewByType(car(identity) cadr(identity) caddr(identity) "maskLayout" "r")
    when(cv
      unwindProtect(result=!dbIsCellViewModified(cv) dbClose(cv))) result))

procedure(ALDGUIQuickSave(win)
  let((cv state)
    state=ALDGUIWindows[win]
    if(!ALDGUIOwner then ALDRuntimePanel()
    else if(state && (state['review] || state['expiredReview]) then
      ALDGUINotice("Save & Commit is available on source layouts, not read-only reviews.")
    else
      cv=when(win win->editCellView)
      if(!cv || cv~>cellViewType!="maskLayout" || cv~>mode=="r" then
        ALDGUINotice("Open an editable layout before using Save & Commit.")
      else
        if(dbSave(cv) then
          ALDGUIEnqueue(list("quick-preview" cv~>libName cv~>cellName cv~>viewName))
        else ALDGUINotice("Layout save failed; no commit preview was created.")))))))

procedure(ALDGUIQuickFocus(form)
  hiSetCurrentField(form 'aldMessage))

procedure(ALDGUIShowQuickPreview(token summary text path)
  let((header preview message full)
    unless(boundp('ALDGUIQuickForm) && ALDGUIQuickForm
      header=hiCreateMLTextField(?name 'aldSummary ?prompt "" ?editable nil
        ?hasHorizontalScrollbar nil ?enableWordWrap t)
      preview=hiCreateMLTextField(?name 'aldPreview ?prompt "" ?editable nil ?enableWordWrap nil)
      message=hiCreateStringField(?name 'aldMessage ?prompt "Commit message" ?value "")
      full=hiCreateButton(?name 'aldFullDiff ?buttonText "View full diff..."
        ?callback "ALDGUIEnqueue(list(\"quick-full\" ALDGUIQuickForm->aldToken))")
      ALDGUIQuickForm=hiCreateAppForm(?name 'ALDGUIQuickForm ?formTitle "Layout Diff - Save & Commit to Git"
        ?fields list(list(header 10:10 900:200) list(preview 10:220 900:290)
          list(full 10:520 180:30) list(message 10:560 900:32 125))
        ?initialSize list(930 660) ?buttonLayout 'OKCancel
        ?callback list('ALDGUIQuickOK 'ALDGUIQuickCancel) ?unmapAfterCB t
        ?mapCB 'ALDGUIQuickFocus ?dontBlock t ?dialogStyle 'modeless))
    ALDGUIQuickForm->aldToken=token
    ALDGUIQuickForm->aldPath=path
    ALDGUIQuickForm->aldSummary->value=summary
    ALDGUIQuickForm->aldPreview->value=text
    ALDGUIQuickForm->aldMessage->value=""
    hiDisplayForm(ALDGUIQuickForm)
    hiSetCurrentField(ALDGUIQuickForm 'aldMessage)))

procedure(ALDGUIQuickOK(form)
  if(form->aldMessage->value=="" then
    hiSetCallbackStatus(form nil)
    hiSetCurrentField(form 'aldMessage)
  else
    when(form->aldToken
      ALDGUIEnqueue(list("quick-commit" form->aldToken form->aldMessage->value))
      form->aldToken=nil)))

procedure(ALDGUIQuickCancel(form)
  when(form->aldToken
    ALDGUIEnqueue(list("quick-cancel" form->aldToken)) form->aldToken=nil))

procedure(ALDGUIQuickOpenFull(token path)
  when(boundp('ALDGUIQuickForm) && ALDGUIQuickForm && ALDGUIQuickForm->aldToken==token
    ALDGUIQuickForm->aldPath=path
    ALDGUIQuickForm->aldFullWindow=hiViewTextFile(path ?title "Layout Diff - Full Commit Preview" ?fixedFont t)))

procedure(ALDGUIPerformance(mode text)
  let((choice status)
    unless(boundp('ALDGUIPerformanceForm) && ALDGUIPerformanceForm
      choice=hiCreateCyclicField(?name 'aldMode ?prompt "Backend" ?choices list("auto" "python" "native"))
      status=hiCreateMLTextField(?name 'aldInfo ?prompt "" ?editable nil ?enableWordWrap t)
      ALDGUIPerformanceForm=hiCreateAppForm(?name 'ALDGUIPerformanceForm ?formTitle "Layout Diff - Performance Backend"
        ?fields list(list(choice 10:10 700:30 110) list(status 10:55 700:245))
        ?initialSize list(740 380) ?buttonLayout 'OKCancelApply
        ?callback "ALDGUIEnqueue(list(\"backend-config\" ALDGUIPerformanceForm->aldMode->value))"
        ?dontBlock t ?dialogStyle 'modeless))
    ALDGUIPerformanceForm->aldMode->value=mode
    ALDGUIPerformanceForm->aldInfo->value=text
    hiDisplayForm(ALDGUIPerformanceForm)))

procedure(ALDGUIShowGitSetup(identity directory name email)
  let((path who address help)
    unless(boundp('ALDGUIGitForm)
      path=hiCreateStringField(?name 'aldRepo ?prompt "Repository directory" ?value "")
      who=hiCreateStringField(?name 'aldName ?prompt "Git author name" ?value "")
      address=hiCreateStringField(?name 'aldEmail ?prompt "Git author email" ?value "")
      help=hiCreateMLTextField(?name 'aldHelp ?prompt "" ?editable nil ?enableWordWrap t
        ?value "Choose a Git repository on the Virtuoso host. If none exists there, OK initializes one. The suggested directory is above the Virtuoso working directory.\nAuthor fields are optional when Git already has an identity; supplied values are saved only in this repository. Cancel creates no repository or commit.")
      ALDGUIGitForm=hiCreateAppForm(?name 'ALDGUIGitForm ?formTitle "Layout Diff - Use or Initialize Git Repository"
        ?fields list(list(help 10:10 810:110) list(path 10:135 810:32 160)
          list(who 10:175 810:32 160) list(address 10:215 810:32 160))
        ?initialSize list(840 320) ?buttonLayout 'OKCancel ?callback 'ALDGUIGitSetupOK
        ?dontBlock t ?dialogStyle 'modeless))
    ALDGUIGitForm->aldSource=identity ALDGUIGitForm->aldRepo->value=directory
    ALDGUIGitForm->aldName->value=name ALDGUIGitForm->aldEmail->value=email
    hiDisplayForm(ALDGUIGitForm) hiSetCurrentField(ALDGUIGitForm 'aldRepo)))

procedure(ALDGUIGitSetupOK(form)
  ALDGUIEnqueue(append(list("git-setup") append(form->aldSource
    list(form->aldRepo->value form->aldName->value form->aldEmail->value)))))

procedure(ALDGUINotice(text)
  let((field full)
    printf("Layout Diff: %s\n" text)
    when(boundp('ALDRuntimeMenu) ALDRuntimeActivity(text))
    unless(boundp('ALDGUIResultForm) && ALDGUIResultForm
      field=hiCreateMLTextField(?name 'aldResult ?prompt "" ?editable nil ?hasHorizontalScrollbar nil ?enableWordWrap t)
      full=hiCreateButton(?name 'aldFullReport ?buttonText "View all unsupported elements..."
        ?callback "ALDGUIOpenUnsupported()")
      ALDGUIResultForm=hiCreateAppForm(?name 'ALDGUIResultForm ?formTitle "Layout Diff - Result"
        ?fields list(list(field 10:10 850:370) list(full 10:390 300:30)) ?initialSize list(880 480)
        ?dontBlock t ?dialogStyle 'modeless ?buttonLayout 'Close))
    ALDGUIResultForm->aldFullReport->enabled=nil
    ALDGUIResultForm->aldResult->value=text
    hiDisplayForm(ALDGUIResultForm)))

procedure(ALDGUIUnsupported(text path summaryPath)
  ALDGUINotice(text)
  ALDGUIResultForm->aldReportPath=path
  ALDGUIResultForm->aldFullReport->enabled=t
  when(summaryPath ALDGUIResultForm->aldSummaryWindow=hiViewTextFile(summaryPath
    ?title "Layout Diff - All Unsupported Categories" ?fixedFont t)))

procedure(ALDGUIStatus(text)
  let((bar)
    printf("Layout Diff: %s\n" text)
    when(boundp('ALDRuntimeMenu) ALDRuntimeActivity(text))
    foreach(win hiGetWindowList()
      when(ALDGUIWindows[win]
        bar=ALDGUIWindows[win]['commitToolbar]
        bar->aldStatus->hiIconText=text))))

procedure(ALDGUIEnqueue(request)
  if(car(request)=="logs" && boundp('ALDRuntimeMenu) then ALDRuntimeLogs()
  else if(ALDGUIOwner && (!boundp('ALDRuntimeState) || ALDRuntimeState=="Running") then
    ALDGUIQueue=append(ALDGUIQueue list(request))
    ALDGUIStatus("Queued...")
  else
    if(boundp('ALDRuntimeMenu) then ALDRuntimePanel()
    else ALDGUINotice("Load the Layout Diff startup.il plugin in CIW.")))))

procedure(ALDGUIIdentity(win)
  let((cv state)
    state=ALDGUIWindows[win]
    if(state && state['source] then state['source]
    else
      cv=when(win win->editCellView)
      when(cv && cv~>cellViewType=="maskLayout"
        list(cv~>libName cv~>cellName cv~>viewName)))))

procedure(ALDGUICommit(win)
  ; Compatibility entry point for old bindkeys; all new commits use Git.
  ALDGUIQuickSave(win))

procedure(ALDGUIQuickSaveIdentity(identity)
  let((target)
    foreach(win hiGetWindowList()
      when(!target && win->editCellView && win->editCellView~>mode!="r" && ALDGUIIdentity(win)==identity
        target=win))
    if(target then ALDGUIQuickSave(target)
    else ALDGUINotice("Open the selected source layout in edit mode, then use Save & Commit."))))

procedure(ALDGUIHistory(win)
  let((identity)
    if(ALDGUIWindows[win] && ALDGUIWindows[win]['expiredReview] then
      ALDGUINotice("This review predates the current runtime. Browse the source history from the Runtime panel to reopen it.")
    else
      identity=ALDGUIIdentity(win)
      when(identity ALDGUIEnqueue(append(list("history") identity))))))

procedure(ALDGUIBrowser()
  ALDGUIEnqueue(append(list("browser") ALDGUIIdentity(hiGetCurrentWindow()))))

procedure(ALDGUIBeginReview(token cv)
  ALDGUIObjects[token]=makeTable('aldReviewObjects nil)
  ALDGUIHeld[token]=dbOpenCellViewByType(cv~>libName cv~>cellName cv~>viewName "maskLayout" "r"))

procedure(ALDGUIRemember(token key object)
  ALDGUIObjects[token][key]=object)

procedure(ALDGUIDiscard(token)
  when(ALDGUIHeld[token] dbClose(ALDGUIHeld[token]) ALDGUIHeld[token]=nil)
  ALDGUIObjects[token]=nil ALDGUIShadowData[token]=nil)

; Independent highlight primitives are required: geAddHilightFig on a figure
; from another cellview returns a handle but draws nothing in this IC23.1 GUI.
; The only database receiving temporary boolean results is the owned helper.
procedure(ALDGUIPrepareShadows(oldToken token keys)
  let((cv o parts primitives fallbacks count primitiveCount box result converted)
    cv=ALDGUIHeld[oldToken]
    unless(cv && dbReopen(cv "a") error("Cannot open deleted-shadow helper"))
    count=0 primitiveCount=0
    foreach(key keys
      o=ALDGUIObjects[oldToken][key]
      unless(o error("Missing deleted review object: %s" key))
      box=ALDGUIUnionBox(box o~>bBox)
      parts=nil
      case(o~>objType
        (("rect" "inst" "mosaic" "stdVia" "prBoundary") parts=list(list("rect" o~>bBox)))
        ("polygon" parts=list(list("polygon" o~>points)))
        ("ellipse" parts=list(list("ellipse" o~>bBox)))
        ("arc" parts=list(list("arc" o~>ellipseBBox o~>bBox)))
        ("donut" parts=list(list("donut" o~>xy o~>outerRadius o~>innerRadius)))
        ("line" parts=list(list("line" o~>points)))
        ("label" parts=list(list("label" o~>xy o~>theLabel o~>justify o~>orient o~>font o~>height o~>isDrafted o~>isOverbar)))
        (t
          ; Native booleans preserve path/custom-chamfer caps. Delete the
          ; derived objects immediately; no source figure is changed.
          converted=nil
          result=errset(progn(
            converted=dbLayerOr(cv o~>layerName list(o))
            foreach(p converted
              if(p~>objType=="rect" then parts=cons(list("rect" p~>bBox) parts)
              else when(p~>points parts=cons(list("polygon" p~>points) parts))))) t)
          foreach(p converted dbDeleteObject(p))
          unless(result && parts
            parts=list(list("rect" o~>bBox))
            fallbacks=cons(list(key o~>objType "Native contour unavailable; bounding box used") fallbacks))))
      primitives=append(parts primitives)
      primitiveCount=primitiveCount+length(parts) count=count+1)
    ALDGUIShadowData[token]=list(box primitives)
    list(count primitiveCount reverse(fallbacks))))

procedure(ALDGUIDrawShadow(hl primitive)
  case(car(primitive)
    ("rect" geAddHilightRectangle(hl cadr(primitive)))
    ("polygon" geAddHilightPolygon(hl cadr(primitive)))
    ("ellipse" geAddHilightEllipse(hl cadr(primitive)))
    ("arc" geAddHilightArc(hl cadr(primitive) caddr(primitive)))
    ("donut" geAddHilightDonut(hl cadr(primitive) caddr(primitive) nth(3 primitive)))
    ("line" geAddHilightLine(hl cadr(primitive)))
    ("label" geAddHilightLabel(hl nth(1 primitive) nth(2 primitive) nth(3 primitive)
      nth(4 primitive) nth(5 primitive) nth(6 primitive) nth(7 primitive) nth(8 primitive)))))

; Only derived review geometry. Empty/non-spatial groups return nil bounds.
procedure(ALDGUIGroupBounds(token requests)
  let((cache box part o)
    cache=makeTable('aldBounds nil)
    foreach(mapcar entry requests
      box=nil
      foreach(key cadr(entry)
        o=ALDGUIObjects[token][key]
        part=cache[key]
        when(!part && o part=o~>bBox cache[key]=part)
        when(part
          if(box then
            box=ALDGUIUnionBox(box part)
          else box=part)))
      list(car(entry) box))))

procedure(ALDGUIUnionBox(a b)
  cond((!a b) (!b a)
    (t list(list(min(caar(a) caar(b)) min(cadar(a) cadar(b)))
            list(max(caadr(a) caadr(b)) max(cadadr(a) cadadr(b)))))))

procedure(ALDGUIToggle(win group)
  let((state hl action)
    state=ALDGUIWindows[win]
    when(state
      hl=state[group]
      when(hl
        state['visible][group]=!state['visible][group]
        action=get(state['toolbar] concat(group))
        hiSetActionChecked(action state['visible][group] nil)
        ALDGUIRefreshBlink()))))

procedure(ALDGUIToggleGroups(win)
  let((state)
    state=ALDGUIWindows[win]
    when(state
      state['groupsEnabled]=!state['groupsEnabled]
      foreach(group '("groupNew" "groupChanged" "groupDeleted")
        state['visible][group]=state['groupsEnabled])
      hiSetActionChecked(state['toolbar]->groups state['groupsEnabled] nil)
      ALDGUIRefreshBlink())))

; User visibility is independent of blink phase. One shared timer changes
; only highlight-set enable flags, never iterating the layout's figures.
procedure(ALDGUIApplyHighlightPhase()
  let((state data enabled blinking active changed)
    foreach(win hiGetWindowList()
      state=ALDGUIWindows[win]
      when(state && state['review] && state['visible]
        changed=nil
        foreach(group ALDGUIHighlightGroups
          when(state[group]
            data=ALDGUIStyleData[state['review]][group]
            blinking=(nth(3 data)=="Blink" && state['populated][group])
            enabled=state['visible][group] && (!blinking || ALDGUIBlinkPhase)
            when(blinking && state['visible][group] active=t)
            unless(state[group]->enable==enabled
              state[group]->enable=enabled changed=t)))
        when(changed hiRedraw(win))))
    active))

procedure(ALDGUIBlinkTick(generation)
  when(ALDGUIOwner && generation==ALDGUIBlinkGeneration
    ALDGUIBlinkScheduled=nil
    ALDGUIBlinkPhase=!ALDGUIBlinkPhase
    when(ALDGUIApplyHighlightPhase()
      ALDGUIBlinkScheduled=hiRegTimer(sprintf(nil "ALDGUIBlinkTick(%d)" generation) 5))))

procedure(ALDGUIRefreshBlink()
  ALDGUIBlinkGeneration=ALDGUIBlinkGeneration+1
  ALDGUIBlinkScheduled=nil ALDGUIBlinkPhase=t
  when(ALDGUIOwner && ALDGUIApplyHighlightPhase()
    ALDGUIBlinkScheduled=hiRegTimer(sprintf(nil "ALDGUIBlinkTick(%d)" ALDGUIBlinkGeneration) 5)))

procedure(ALDGUIStyles(win)
  let((state group items row col field data columns grid)
    state=ALDGUIWindows[win]
    when(state && state['review]
      unless(boundp('ALDGUIStyleForm) && ALDGUIStyleForm
        columns='(("Color" "Gray" "Orange" "Green" "Cyan" "Magenta" "Yellow" "Blue" "Red")
          ("Wire style" "Solid" "Dashed" "Dotted" "Dash-dot") ("Width (px)" "1" "2" "3" "5") ("Animation" "Steady" "Blink"))
        col=0
        foreach(title '("Category" "Color" "Wire style" "Width (px)" "Animation")
          field=hiCreateLabel(?name concat("aldHeader" col) ?labelText title)
          items=cons(list(field 'row 0 'col col) items) col=col+1)
        row=1
        foreach(choice ALDGUIStyleChoices
          group=cadr(choice)
          field=hiCreateLabel(?name concat("aldLabel" group) ?labelText car(choice))
          items=cons(list(field 'row row 'col 0) items)
          col=0
          foreach(column columns
            field=hiCreateCyclicField(?name concat("aldStyle_" group "_" col) ?prompt "" ?choices cdr(column))
            items=cons(list(field 'row row 'col col+1) items) col=col+1)
          row=row+1)
        grid=hiCreateGridLayout('aldStyleGrid ?items reverse(items) ?spacing 10 ?margins list(12 12 12 12))
        ALDGUIStyleForm=hiCreateLayoutForm('ALDGUIStyleForm "Layout Diff - Highlight Styles" grid
          ?minSize list(660 370) ?buttonLayout 'OKCancelApply
          ?callback 'ALDGUIStyleCB ?dialogStyle 'modeless))
      ALDGUIStyleForm->aldToken=state['review]
      foreach(group ALDGUIHighlightGroups
        data=ALDGUIStyleData[state['review]][group]
        for(col 0 3
          field=get(ALDGUIStyleForm concat("aldStyle_" group "_" col))
          field->value=nth(col data)))
      hiDisplayForm(ALDGUIStyleForm))))

procedure(ALDGUIStyleCB(form)
  let((rows settings field col)
    foreach(group ALDGUIHighlightGroups
      settings=nil
      for(col 0 3
        field=get(form concat("aldStyle_" group "_" col))
        settings=cons(field->value settings))
      rows=cons(cons(group reverse(settings)) rows))
    ALDGUIEnqueue(list("styles" form->aldToken reverse(rows)))))

procedure(ALDGUIAttach(win)
  let((cv bar state n)
    ; hiGetWindowList includes CIW and text viewers. The documented window
    ; property is nil for those; calling geGetWindowCellView emits GE-2067.
    cv=when(win win->displayCellView)
    when(cv && cv~>cellViewType=="maskLayout" && !ALDGUIWindows[win]
      n=win~>windowNum
      bar=hiCreateToolbar(?name concat(sprintf(nil "aldToolbar%d" n)) ?title "Layout Diff"
        ?toolButtonStyle 'textBesideIcon
        ?items list(
          hiCreateAction(?name 'aldQuickCommit ?iconText "Save && Commit"
            ?toolTip strcat("Save layout and preview a Git commit. Shortcut: " or(ALDGUIQuickKey "none available"))
            ?callback sprintf(nil "ALDGUIQuickSave(window(%d))" n))
          hiCreateAction(?name 'aldHistory ?iconText "History" ?callback sprintf(nil "ALDGUIHistory(window(%d))" n))
          hiCreateAction(?name 'aldRuntime ?iconText "Runtime" ?callback "ALDRuntimePanel()")
          hiCreateAction(?name 'aldStatus ?iconText "Ready" ?enabled nil ?callback "t")))
      state=makeTable('aldWindowState nil) state['toolbar]=bar state['commitToolbar]=bar
      when(strlen(cv~>cellName)==27 && substring(cv~>cellName 1 11)=="ALD_REVIEW_"
        state['expiredReview]=t)
      ALDGUIWindows[win]=state
      hiPlaceToolbarBreak(win 'top)
      hiPlaceToolbar(win bar 'top))))

procedure(ALDGUIAttachAll()
  let((live)
    live=hiGetWindowList()
    foreach(win ALDGUIKnownWindows
      unless(member(win live)
        when(ALDGUIWindows[win] && ALDGUIWindows[win]['review]
          ALDGUIStyleData[ALDGUIWindows[win]['review]]=nil
          ALDGUIReviews[ALDGUIWindows[win]['review]]=nil)
        ALDGUIWindows[win]=nil))
    ALDGUIKnownWindows=live
    foreach(win live ALDGUIAttach(win)) t))

procedure(ALDGUIFit(win)
  let((cv box pad)
    cv=when(win win->displayCellView)
    box=or(when(ALDGUIWindows[win] ALDGUIWindows[win]['reviewBox]) when(cv cv~>bBox))
    when(box
      pad=max(0.2 (caadr(box)-caar(box))*0.15 (cadadr(box)-cadar(box))*0.15)
      hiZoomIn(win list(list(caar(box)-pad cadar(box)-pad) list(caadr(box)+pad cadadr(box)+pad))))))

procedure(ALDGUIOpenReview(token lib cell source assignments packets icons summary outlines)
  let((win state bar hl o group n)
    when(dbIsCellViewModified(ALDGUIHeld[token]) error("Review must be saved before opening read-only"))
    unless(dbReopen(ALDGUIHeld[token] "r") error("Cannot set review cell read-only"))
    win=deOpenCellView(lib cell "layout" "maskLayout" nil "r")
    unless(win error("Cannot open review window"))
    ALDGUIAttach(win)
    state=ALDGUIWindows[win] state['review]=token state['source]=source
    state['expiredReview]=nil
    state['summary]=summary
    state['reviewBox]=win->displayCellView~>bBox
    state['reviewBox]=ALDGUIUnionBox(state['reviewBox] car(ALDGUIShadowData[token]))
    foreach(entry outlines state['reviewBox]=ALDGUIUnionBox(state['reviewBox] cadr(entry)))
    ALDGUIReviews[token]=win
    n=win~>windowNum
    state['visible]=makeTable('aldVisible nil)
    state['populated]=makeTable('aldPopulated nil)
    foreach(group ALDGUIHighlightGroups
      hl=geCreateWindowHilightSet(win cadr(assoc(group packets)) nil)
      unless(hl error("Cannot create review highlight set"))
      state[group]=hl
      foreach(entry assignments
        when(cadr(entry)==group
          o=ALDGUIObjects[token][car(entry)]
          when(o
            state['populated][group]=t
            if(member(o~>objType '("mosaic" "stdVia" "prBoundary")) then
              geAddHilightRectangle(hl o~>bBox)
            else geAddHilightFig(hl o nil)))))
      foreach(entry outlines
        when(car(entry)==group geAddHilightRectangle(hl cadr(entry)) state['populated][group]=t))
      when(group=="deleted"
        foreach(primitive cadr(ALDGUIShadowData[token])
          unless(ALDGUIDrawShadow(hl primitive) error("Cannot draw deleted-object shadow"))
          state['populated][group]=t))
      state['visible][group]=t
      hl->enable=t)
    state['groupsEnabled]=t
    bar=hiCreateToolbar(?name concat(sprintf(nil "aldReviewToolbar%d" n)) ?title "Layout Diff Review"
      ?toolButtonStyle 'textBesideIcon
      ?items list(
        hiCreateAction(?name 'untouched ?iconText "Untouched" ?icon cadr(assoc("untouched" icons))
          ?checkable t ?checked t ?callback sprintf(nil "ALDGUIToggle(window(%d) \"untouched\")" n))
        hiCreateAction(?name 'changed ?iconText "Modified" ?icon cadr(assoc("changed" icons))
          ?checkable t ?checked t ?callback sprintf(nil "ALDGUIToggle(window(%d) \"changed\")" n))
        hiCreateAction(?name 'netChanged ?iconText "Modified net" ?icon cadr(assoc("netChanged" icons))
          ?checkable t ?checked t ?callback sprintf(nil "ALDGUIToggle(window(%d) \"netChanged\")" n))
        hiCreateAction(?name 'new ?iconText "New" ?icon cadr(assoc("new" icons))
          ?checkable t ?checked t ?callback sprintf(nil "ALDGUIToggle(window(%d) \"new\")" n))
        hiCreateAction(?name 'deleted ?iconText "Deleted" ?icon cadr(assoc("deleted" icons))
          ?checkable t ?checked t ?callback sprintf(nil "ALDGUIToggle(window(%d) \"deleted\")" n))
        hiCreateAction(?name 'groups ?iconText "Groups" ?toolTip "Toggle new, modified and deleted group boundaries"
          ?checkable t ?checked t ?callback sprintf(nil "ALDGUIToggleGroups(window(%d))" n))
        hiCreateAction(?name 'aldStyle ?iconText "Style..." ?callback sprintf(nil "ALDGUIStyles(window(%d))" n))
        hiCreateAction(?name 'aldFit ?iconText "Fit" ?callback sprintf(nil "ALDGUIFit(window(%d))" n))
        hiCreateAction(?name 'aldSummary ?iconText "Summary" ?callback sprintf(nil "ALDGUINotice(ALDGUIWindows[window(%d)]['summary])" n))))
    state['toolbar]=bar
    hiPlaceToolbarBreak(win 'bottom)
    hiPlaceToolbar(win bar 'bottom)
    ALDGUIDiscard(token)
    ALDGUIRefreshBlink()
    hiRedraw(win)
    win~>windowNum))

procedure(ALDGUIUpdateStyle(token group data icon)
  ALDGUIUpdateStyles(token list(list(group data icon))))

procedure(ALDGUIUpdateStyles(token updates)
  let((win state action)
    win=ALDGUIReviews[token]
    state=when(member(win hiGetWindowList()) ALDGUIWindows[win])
    foreach(entry updates
      ALDGUIStyleData[token][car(entry)]=cadr(entry)
      when(state
        action=get(state['toolbar] concat(car(entry)))
        when(action action->hiIcon=caddr(entry))))
    when(state ALDGUIRefreshBlink() hiRedraw(win))))

procedure(ALDGUIPoll(owner)
  let((requests)
    unless(ALDGUIOwner==owner error("Layout Diff worker session replaced"))
    ALDGUIAttachAll()
    requests=ALDGUIQueue ALDGUIQueue=nil
    requests))

procedure(ALDGUIStop(owner)
  when(ALDGUIOwner==owner
    ALDGUIBlinkGeneration=ALDGUIBlinkGeneration+1 ALDGUIBlinkScheduled=nil
    when(ALDGUIQuickKey
      when(hiGetBindKey("Layout" ALDGUIQuickKey)=="ALDGUIQuickSave(hiGetCurrentWindow())"
        hiSetBindKey("Layout" ALDGUIQuickKey ""))
      ALDGUIQuickKey=nil)
    when(boundp('ALDGUIQuickForm) && ALDGUIQuickForm hiFormCancel(ALDGUIQuickForm))
    when(boundp('ALDGUIGitForm) && ALDGUIGitForm hiFormCancel(ALDGUIGitForm))
    foreach(token ALDGUIHeld ALDGUIDiscard(token))
    when(boundp('ALDGUICommitForm) && ALDGUICommitForm hiFormCancel(ALDGUICommitForm))
    when(boundp('ALDGUIHistoryForm) && ALDGUIHistoryForm hiFormCancel(ALDGUIHistoryForm))
    when(boundp('ALDGUIStyleForm) && ALDGUIStyleForm hiFormCancel(ALDGUIStyleForm))
    when(boundp('ALDGUIResultForm) && ALDGUIResultForm hiFormCancel(ALDGUIResultForm))
    when(boundp('ALDGUIPerformanceForm) && ALDGUIPerformanceForm hiFormCancel(ALDGUIPerformanceForm))
    foreach(win hiGetWindowList()
      let((state)
        state=ALDGUIWindows[win]
        when(state
          foreach(group ALDGUIHighlightGroups
            when(state[group] geDeleteHilightSet(state[group])))
          hiDeleteToolbarBreak(win concat(sprintf(nil "aldToolbar%d" win~>windowNum)))
          hiDeleteToolbar(win concat(sprintf(nil "aldToolbar%d" win~>windowNum)))
          when(state['review]
            hiDeleteToolbarBreak(win concat(sprintf(nil "aldReviewToolbar%d" win~>windowNum)))
            hiDeleteToolbar(win concat(sprintf(nil "aldReviewToolbar%d" win~>windowNum)))))))
    ALDGUIWindows=makeTable('aldGuiWindows nil)
    ALDGUIReviews=makeTable('aldGuiReviews nil)
    ALDGUIStyleData=makeTable('aldGuiStyles nil)
    ALDGUIOwner=nil ALDGUIQueue=nil)
  t)

procedure(ALDGUIOpenUnsupported()
  when(boundp('ALDGUIResultForm) && ALDGUIResultForm && ALDGUIResultForm->aldReportPath
    ALDGUIResultForm->aldReportWindow=hiViewTextFile(ALDGUIResultForm->aldReportPath
      ?title "Layout Diff - Unsupported Elements" ?fixedFont t)))
