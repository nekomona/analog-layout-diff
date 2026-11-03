; Native graphical merge workspace. Callbacks only enqueue versioned requests.
; Result and alternative cells are session-owned; source layouts are never opened for edit.
unless(boundp('ALDMergeSessions) ALDMergeSessions=makeTable('aldMergeSessions nil))

procedure(ALDMergeRequest(token action @optional (value ""))
  let((s)
    s=ALDMergeSessions[token]
    when(s && !s['loading]
      ALDGUIEnqueue(list("merge-action" token s['generation] action value)))))

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

procedure(ALDMergeClose(token @optional (closeEditor nil))
  let((s)
    s=ALDMergeSessions[token]
    when(s
      foreach(hl s['highlights] geDeleteHilightSet(hl))
      foreach(dw s['docks] hiCloseWindow(dw))
      foreach(field '(navigation decision details)
        when(s[field] hiDeleteForm(s[field])))
      when(closeEditor && member(s['window] hiGetWindowList())
        let((cv)
          cv=s['window]->editCellView
          when(cv && cv~>libName==s['library] && cv~>cellName==s['cell]
            ; Save only this disposable cell to avoid a close-time modal prompt.
            when(dbIsCellViewModified(cv) dbSave(cv))
            hiCloseWindow(s['window]))))
      ALDMergeSessions[token]=nil)))

procedure(ALDMergeOpen(token lib cell generation summary)
  let((s win session form fields rows detail choice status bar dw n action fields2 form2)
    win=deOpenCellView(lib cell "layout" "maskLayout" nil "r")
    unless(win error("Cannot open merge result"))
    session=hiGetSessionWindow(win)
    unless(session error("A Virtuoso session window is required for merge panels"))
    ALDMergeClose(token t)
    n=win~>windowNum s=makeTable('aldMerge nil)
    s['window]=win s['generation]=generation s['docks]=nil s['highlights]=nil
    s['library]=lib s['cell]=cell s['visible]=list(t t t) s['blink]=nil s['phase]=t
    ALDMergeSessions[token]=s win->aldMergeToken=token
    ; Prevent ordinary Save & Commit from treating the temporary result as a source.
    ALDGUIAttach(win) ALDGUIWindows[win]['expiredReview]=t
    rows=hiCreateReportField(?name 'aldConflicts ?title "MERGE DECISIONS" ?selectMode 'single
      ?headers '(("ID" 70 left string nil) ("Category" 145 left string nil) ("State" 85 left string nil))
      ?choices nil ?callback sprintf(nil "ALDMergeSelect(%s)" concat("aldMergeNav" n)))
    status=hiCreateMLTextField(?name 'aldStatus ?prompt "" ?editable nil ?value summary)
    fields=list(list(status 8:8 324:90 0) list(rows 8:106 324:370 0))
    form=hiCreateAppForm(?name concat("aldMergeNav" n) ?formTitle "Layout Merge"
      ?fields fields ?buttonLayout 'Empty ?initialSize list(340 490))
    form->aldToken=token s['navigation]=form
    dw=hiCreateDockWindow(?appType "form" ?widgetType "form" ?form form
      ?title "Merge navigation" ?dockSizeHint list(350 520))
    hiDockWindow(?window dw ?session session ?side 'left) s['docks]=cons(dw s['docks])
    detail=hiCreateMLTextField(?name 'aldExplanation ?prompt "" ?editable nil ?value "Select a conflict in the panel or canvas.")
    choice=hiCreateCyclicField(?name 'aldChoice ?prompt "Alternative" ?choices list("target" "incoming" "base" "combined" "both"))
    fields2=list(list(detail 8:8 324:170 0) list(choice 8:186 324:28 85))
    foreach(pair '(("Preview" "preview") ("Accept preview" "accept") ("Edit result" "edit")
        ("Accept edits" "accept-edits") ("Cancel edits" "cancel-edits") ("Serialized preview" "details"))
      action=hiCreateButton(?name concat("aldMergeButton" length(fields2)) ?buttonText car(pair)
        ?callback sprintf(nil "ALDMergeRequest(%L %L %s->aldChoice->value)" token cadr(pair) concat("aldMergeDecision" n)))
      fields2=append(fields2 list(list(action list(8 225+36*(length(fields2)-2)) list(324 30)))))
    form2=hiCreateAppForm(?name concat("aldMergeDecision" n) ?formTitle "Merge decision"
      ?fields fields2 ?buttonLayout 'Empty ?initialSize list(340 460))
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
    hiZoomIn(win win->displayCellView~>bBox)
    win))

procedure(ALDMergeUpdate(token generation rows summary explanation)
  let((s form)
    s=ALDMergeSessions[token]
    when(s
      s['generation]=generation form=s['navigation] form->aldUpdating=t
      form->aldConflicts->choices=rows form->aldStatus->value=summary
      s['decision]->aldExplanation->value=explanation form->aldUpdating=nil)))

procedure(ALDMergeBusy(token message)
  let((s)
    s=ALDMergeSessions[token]
    when(s s['loading]=(message!="")
      when(message!="" s['navigation]->aldStatus->value=strcat("Loading: " message)))))

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
    hiRedraw(s['window]) t))

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
    when(s s['blink]=!s['blink] s['phase]=t ALDMergeAnimate(token t))))

procedure(ALDMergeAnimate(token scheduled)
  let((s n)
    s=ALDMergeSessions[token]
    when(s && member(s['window] hiGetWindowList())
      when(scheduled && s['blink] s['phase]=!s['phase])
      n=0 foreach(hl s['highlights]
        hl->enable=nth(n s['visible]) && (!s['blink] || s['phase]) n=n+1)
      hiRedraw(s['window])
      when(scheduled && s['blink] hiRegTimer(sprintf(nil "ALDMergeAnimate(%L t)" token) 5)))))

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
