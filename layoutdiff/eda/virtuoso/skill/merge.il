; Native graphical merge workspace. Callbacks only enqueue versioned requests.
; Result and alternative cells are session-owned; source layouts are never opened for edit.
unless(boundp('ALDMergeSessions) ALDMergeSessions=makeTable('aldMergeSessions nil))
unless(boundp('ALDMergeLeases) ALDMergeLeases=makeTable('aldMergeLeases nil))
unless(boundp('ALDMergeMissing) ALDMergeMissing=makeTable('aldMergeMissing 0))
unless(boundp('ALDMergeWatchTimer) ALDMergeWatchTimer=nil)
unless(boundp('ALDMergeAnimationSerial) ALDMergeAnimationSerial=0)

procedure(ALDMergeHold(token lease)
  ALDGUILeases[lease]['hold]=t
  ALDMergeLeases[token]=cons(lease ALDMergeLeases[token])
  ALDMergeMissing[token]=0
  unless(ALDMergeWatchTimer ALDMergeWatchTimer=t hiRegTimer("ALDMergeWatch()" 10)))

procedure(ALDMergeRelease(token lease)
  when(ALDGUILeases[lease] ALDGUILeases[lease]['hold]=nil)
  ALDMergeLeases[token]=remove(lease ALDMergeLeases[token]))

procedure(ALDMergeWatch()
  let((s pending)
    ALDMergeWatchTimer=nil
    foreach(token ALDMergeLeases
      when(ALDMergeLeases[token]
        s=ALDMergeSessions[token]
        if(s then
          unless(member(s['window] hiGetWindowList()) ALDMergeClose(token))
        else
          ALDMergeMissing[token]=ALDMergeMissing[token]+1
          when(ALDMergeMissing[token]>120 ALDMergeClose(token)))
        when(ALDMergeLeases[token] pending=t)))
    when(pending ALDMergeWatchTimer=t hiRegTimer("ALDMergeWatch()" 10))))

procedure(ALDMergeRequest(token action @optional (value ""))
  let((s)
    s=ALDMergeSessions[token]
    when(s && !s['loading]
      ALDGUIEnqueue(list("merge-action" token s['generation] action value)))))

procedure(ALDMergeAlive(token)
  let((s) s=ALDMergeSessions[token]
    when(s && member(s['window] hiGetWindowList()) t)))

procedure(ALDMergeSelect(form)
  when(!form->aldUpdating && form->aldConflicts->value
    ALDMergeRequest(form->aldToken "select" car(nth(car(form->aldConflicts->value) form->aldConflicts->choices)))))

procedure(ALDMergePickDone(win done points)
  let((token s)
    token=win->aldMergeToken s=when(token ALDMergeSessions[token])
    when(done && s && points
      ALDMergeRequest(token "pick" car(points)))))

procedure(ALDMergePick(token)
  let((s)
    s=ALDMergeSessions[token]
    when(s && member(s['window] hiGetWindowList())
      hiSetCurrentWindow(s['window])
      enterPoint(?prompts list("Select a merge conflict or alternative. Escape cancels.")
        ?doneProc "ALDMergePickDone" ?cmdName "Layout Diff Merge Pick"))))

procedure(ALDMergeClose(token @optional (closeEditor nil) (keepLeases nil))
  let((s)
    s=ALDMergeSessions[token]
    when(s
      foreach(hl s['highlights] errset(geDeleteHilightSet(hl) nil))
      foreach(dw s['docks] when(member(dw hiGetWindowList()) hiCloseWindow(dw)))
      foreach(field '(navigation decision details)
        when(s[field] hiDeleteForm(s[field])))
      when(closeEditor && member(s['window] hiGetWindowList())
        let((cv)
          cv=s['window]->editCellView
          when(cv && cv~>libName==s['library] && cv~>cellName==s['cell]
            ; Save only this disposable cell to avoid a close-time modal prompt.
            when(dbIsCellViewModified(cv) dbSave(cv))
            hiCloseWindow(s['window]))))
      ALDMergeSessions[token]=nil)
    unless(keepLeases
      foreach(lease ALDMergeLeases[token] when(ALDGUILeases[lease] ALDGUILeases[lease]['hold]=nil))
      ALDMergeLeases[token]=nil)))

procedure(ALDMergeOpen(token lib cell generation summary)
  let((s win session form fields rows detail choice status bar dw n action fields2 form2 visible blink filter frameBox)
    s=ALDMergeSessions[token]
    frameBox=if(s && member(s['window] hiGetWindowList()) then
      hiGetAbsWindowScreenBBox(s['window] t) else list(20:20 1420:920))
    win=deOpenCellView(lib cell "layout" "maskLayout" nil "r")
    unless(win error("Cannot open merge result"))
    hiResizeWindow(win frameBox)
    session=hiGetSessionWindow(win)
    unless(session error("A Virtuoso session window is required for merge panels"))
    s=ALDMergeSessions[token]
    visible=if(s then s['visible] else list(t t t)) blink=when(s s['blink])
    ALDMergeClose(token t t)
    n=win~>windowNum s=makeTable('aldMerge nil)
    s['window]=win s['generation]=generation s['docks]=nil s['highlights]=nil
    s['library]=lib s['cell]=cell s['visible]=visible s['blink]=blink s['phase]=t
    ALDMergeAnimationSerial=ALDMergeAnimationSerial+1 s['animation]=ALDMergeAnimationSerial
    ALDMergeSessions[token]=s win->aldMergeToken=token
    ; Prevent ordinary Save & Commit from treating the temporary result as a source.
    ALDGUIAttach(win) ALDGUIWindows[win]['expiredReview]=t
    rows=hiCreateReportField(?name 'aldConflicts ?title "MERGE DECISIONS" ?selectMode 'single
      ?headers '(("ID" 0 left string nil) ("Category" 110 left string nil) ("State" 75 left string nil))
      ?choices nil ?callback sprintf(nil "ALDMergeSelect(%s)" concat("aldMergeNav" n)))
    status=hiCreateMLTextField(?name 'aldStatus ?prompt "" ?editable nil ?value summary ?enableWordWrap t ?hasHorizontalScrollbar nil)
    filter=hiCreateCyclicField(?name 'aldCategory ?prompt "Category" ?choices list("All")
      ?callback sprintf(nil "unless(%s->aldUpdating ALDMergeRequest(%L \"category\" %s->aldCategory->value))"
        concat("aldMergeNav" n) token concat("aldMergeNav" n)))
    fields=list(list(status 8:8 324:90 0) list(filter 8:102 324:28 70) list(rows 8:138 324:300 0)
      list(hiCreateButton(?name 'aldPagePrevious ?buttonText "Previous page"
        ?callback sprintf(nil "ALDMergeRequest(%L \"page-previous\")" token)) 8:448 158:30)
      list(hiCreateButton(?name 'aldPageNext ?buttonText "Next page"
        ?callback sprintf(nil "ALDMergeRequest(%L \"page-next\")" token)) 174:448 158:30))
    form=hiCreateLayoutForm(concat("aldMergeNav" n) "Layout Merge"
      hiCreateVerticalBoxLayout(concat("aldMergeNavLayout" n) ?margins list(8 8 8 8) ?spacing 4 ?scrollable t
        ?items foreach(mapcar field fields car(field))) ?buttonLayout 'Empty ?initialSize list(340 490))
    form->aldToken=token s['navigation]=form
    dw=hiCreateDockWindow(?appType "form" ?widgetType "form" ?form form
      ?title "Merge navigation" ?dockSizeHint list(350 520))
    hiDockWindow(?window dw ?session session ?side 'left) s['docks]=cons(dw s['docks])
    detail=hiCreateMLTextField(?name 'aldExplanation ?prompt "" ?editable nil ?enableWordWrap t ?hasHorizontalScrollbar nil
      ?value "Select a conflict in the panel or canvas.")
    choice=hiCreateCyclicField(?name 'aldChoice ?prompt "Alternative" ?choices list("target" "incoming" "base" "combined" "both"))
    fields2=list(list(detail 8:8 324:170 0) list(choice 8:186 324:28 85))
    foreach(pair '(("Preview" "preview") ("Accept preview" "accept") ("Edit result" "edit")
        ("Accept edits" "accept-edits") ("Cancel edits" "cancel-edits") ("Serialized preview" "details"))
      when(cadr(pair)=="details"
        fields2=append(fields2 list(list(hiCreateSeparatorField(?name 'aldDetailsSeparator)))))
      action=hiCreateButton(?name concat("aldMergeButton" length(fields2)) ?buttonText car(pair)
        ?callback sprintf(nil "ALDMergeRequest(%L %L %s->aldChoice->value)" token cadr(pair) concat("aldMergeDecision" n)))
      fields2=append(fields2 list(list(action list(8 225+36*(length(fields2)-2)) list(324 30)))))
    form2=hiCreateLayoutForm(concat("aldMergeDecision" n) "Merge decision"
      hiCreateVerticalBoxLayout(concat("aldMergeDecisionLayout" n) ?margins list(8 8 8 8) ?spacing 4 ?scrollable t
        ?items foreach(mapcar field fields2 car(field))) ?buttonLayout 'Empty ?initialSize list(340 460))
    form2->aldToken=token s['decision]=form2
    dw=hiCreateDockWindow(?appType "form" ?widgetType "form" ?form form2
      ?title "Decision and result" ?dockSizeHint list(350 500))
    hiDockWindow(?window dw ?session session ?side 'right) s['docks]=cons(dw s['docks])
    bar=hiCreateToolbar(?name concat("aldMergeBar" n) ?title "Layout Merge" ?toolButtonStyle 'textBesideIcon ?items
      append(list(
        hiCreateAction(?name 'aldMergePick ?iconText "Pick" ?callback sprintf(nil "ALDMergePick(%L)" token))
        hiCreateAction(?name 'aldMergeBase ?iconText "Base" ?callback sprintf(nil "ALDMergeToggle(%L 0)" token))
        hiCreateAction(?name 'aldMergeTarget ?iconText "Target" ?callback sprintf(nil "ALDMergeToggle(%L 1)" token))
        hiCreateAction(?name 'aldMergeIncoming ?iconText "Incoming" ?callback sprintf(nil "ALDMergeToggle(%L 2)" token))
        hiCreateAction(?name 'aldMergeBlink ?iconText "Blink" ?callback sprintf(nil "ALDMergeBlink(%L)" token)))
      foreach(mapcar pair '(("Previous" "previous") ("Next" "next") ("Undo decision" "undo")
          ("Redo decision" "redo") ("Validate" "validate") ("Finish merge" "finish") ("Suspend" "suspend"))
        hiCreateAction(?name concat("aldMerge" cadr(pair)) ?iconText car(pair)
          ?callback sprintf(nil "ALDMergeRequest(%L %L)" token cadr(pair))))))
    hiPlaceToolbar(win bar 'top)
    s['toolbar]=bar
    when(s['blink] ALDMergeAnimate(token t s['animation]))
    hiZoomIn(win win->displayCellView~>bBox)
    win))

procedure(ALDMergeCategories(token categories selected)
  let((s form)
    s=ALDMergeSessions[token]
    when(s
      form=s['navigation] form->aldUpdating=t
      form->aldCategory->choices=cons("All" categories) form->aldCategory->value=selected
      form->aldUpdating=nil)))

procedure(ALDMergeUpdate(token generation rows summary explanation)
  let((s form)
    s=ALDMergeSessions[token]
    when(s
      s['generation]=generation form=s['navigation] form->aldUpdating=t
      s['summary]=summary
      form->aldConflicts->choices=rows form->aldStatus->value=summary
      s['decision]->aldExplanation->value=explanation form->aldUpdating=nil)))

procedure(ALDMergeBusy(token message)
  let((s)
    s=ALDMergeSessions[token]
    when(s s['loading]=(message!="")
      s['navigation]->aldStatus->value=if(message!="" then strcat("Loading: " message) else or(s['summary] "Ready")))))

procedure(ALDMergeDraw(token entries)
  let((s hl box)
    s=ALDMergeSessions[token]
    unless(s error("Merge window is closed"))
    foreach(old s['highlights] geDeleteHilightSet(old)) s['highlights]=nil
    foreach(entry entries
      hl=geCreateWindowHilightSet(s['window] car(entry) nil)
      unless(hl error("Cannot create merge highlights"))
      s['highlights]=append(s['highlights] list(hl))
      foreach(primitive cadr(entry) ALDGUIDrawShadow(hl primitive))
      hl->enable=t)
    ALDMergeAnimate(token nil) t))

procedure(ALDMergeZoom(token box)
  let((s pad)
    s=ALDMergeSessions[token]
    when(s && box
      pad=max(0.2 (caadr(box)-caar(box))*0.2 (cadadr(box)-cadar(box))*0.2)
      hiZoomIn(s['window] list(list(caar(box)-pad cadar(box)-pad) list(caadr(box)+pad cadadr(box)+pad))))))

procedure(ALDMergeEdit(token enabled)
  let((s cv)
    s=ALDMergeSessions[token] unless(s error("Merge workspace is closed"))
    cv=s['window]->editCellView
    unless(cv && cv~>libName==s['library] && cv~>cellName==s['cell]
      error("Merge editor no longer shows the owned result"))
    ; geChangeEditMode raises a modal confirmation in Layout XL. Reopen this
    ; explicitly owned temporary database directly; never change source modes.
    when(!enabled && dbIsCellViewModified(cv) dbSave(cv))
    unless(dbReopen(cv if(enabled then "a" else "r")) error("Cannot change merge result mode"))
    hiRedraw(s['window]) t))

procedure(ALDMergeToggle(token index)
  let((s)
    s=ALDMergeSessions[token]
    when(s
      setcar(nthcdr(index s['visible]) !nth(index s['visible]))
      ALDMergeAnimate(token nil))))

procedure(ALDMergeBlink(token)
  let((s)
    s=ALDMergeSessions[token]
    when(s
      ALDMergeAnimationSerial=ALDMergeAnimationSerial+1 s['animation]=ALDMergeAnimationSerial
      s['blink]=!s['blink] s['phase]=t ALDMergeAnimate(token t s['animation]))))

procedure(ALDMergeAnimate(token scheduled @optional generation)
  let((s n)
    s=ALDMergeSessions[token]
    when(s && member(s['window] hiGetWindowList()) && (!scheduled || generation==s['animation])
      when(scheduled && s['blink] s['phase]=!s['phase])
      n=0 foreach(hl s['highlights]
        hl->enable=nth(n s['visible]) && (!s['blink] || s['phase]) n=n+1)
      hiRedraw(s['window])
      when(scheduled && s['blink] hiRegTimer(sprintf(nil "ALDMergeAnimate(%L t %d)" token generation) 5)))))

procedure(ALDMergeDetails(token text)
  let((s field form dw)
    s=ALDMergeSessions[token]
    when(s
      if(s['details] then s['details]->aldText->value=text
      else
        field=hiCreateMLTextField(?name 'aldText ?prompt "" ?editable nil ?enableWordWrap nil ?value text)
        form=hiCreateAppForm(?name concat("aldMergeDetails" s['window]~>windowNum)
          ?formTitle "Serialized merge preview" ?fields list(list(field 8:8 850:230 0))
          ?buttonLayout 'Empty ?initialSize list(870 250))
        s['details]=form
        dw=hiCreateDockWindow(?appType "form" ?widgetType "form" ?form form
          ?title "Serialized preview (optional)" ?dockSizeHint list(880 260))
        hiDockWindow(?window dw ?session hiGetSessionWindow(s['window]) ?side 'bottom)
        s['docks]=cons(dw s['docks])))))

procedure(ALDMergeOmissionPrompt(token phase text)
  let((form yes no body)
    body=hiCreateMLTextField(?name 'aldWarning ?prompt "" ?editable nil ?value text)
    yes=hiCreateButton(?name 'aldContinue ?buttonText if(phase==1 then "Continue ignoring elements" else "Confirm loss and accept edits")
      ?callback sprintf(nil "hiFormCancel(aldMergeOmission) ALDMergeRequest(%L %L)" token if(phase==1 then "omit-continue" else "omit-confirm")))
    no=hiCreateButton(?name 'aldReject ?buttonText "Reject" ?callback sprintf(nil
      "hiFormCancel(aldMergeOmission) ALDMergeRequest(%L \"omit-cancel\")" token))
    when(boundp('aldMergeOmission) && aldMergeOmission hiFormCancel(aldMergeOmission) hiDeleteForm(aldMergeOmission))
    form=hiCreateAppForm(?name 'aldMergeOmission ?formTitle "Merge result contains unsupported elements"
      ?fields list(list(body 10:10 600:180 0) list(no 10:200 170:35) list(yes 200:200 410:35))
      ?buttonLayout 'Empty ?dontBlock t ?dialogStyle 'modeless ?initialSize list(630 270))
    hiDisplayForm(form)))
