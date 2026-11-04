; Repository setup and progress. Geometry decisions stay in the native editor.
; Rebuild form fields on upgrade; durable decisions belong to the worker journal.
when(boundp('ALDMergeRepositoryForm) && ALDMergeRepositoryForm
  hiFormCancel(ALDMergeRepositoryForm) hiDeleteForm(ALDMergeRepositoryForm) ALDMergeRepositoryForm=nil)

procedure(ALDMergeRepoRequest(action @optional (value ""))
  when(boundp('ALDMergeRepositoryForm) && ALDMergeRepositoryForm
    ALDMergeRepositoryForm->aldSummary->value=strcat("Loading: " action)
    ALDGUIEnqueue(list("merge-repository" action ALDMergeRepositoryForm->aldToken value ALDMergeRepositoryForm->aldStamp))))

procedure(ALDMergeRow(field)
  when(field->value car(nth(car(field->value) field->choices))))

procedure(ALDMergeSetup(repo branch refs sessions @optional (activeText "") (activeStamp "") activeEnabled)
  let((fields info incoming rows start resume form active)
    when(boundp('ALDMergeSetupForm) && ALDMergeSetupForm
      hiFormCancel(ALDMergeSetupForm) hiDeleteForm(ALDMergeSetupForm))
    info=hiCreateMLTextField(?name 'aldInfo ?prompt "" ?editable nil ?hasHorizontalScrollbar nil ?enableWordWrap t ?value
      strcat("Repository: " repo "\nTarget: " branch "\n"
        if(activeStamp!="" then activeText else strcat("Branches: " sprintf(nil "%L" refs)
          "\nEnter incoming branches in integration order, separated by spaces. Each step creates a two-parent commit."))))
    incoming=hiCreateStringField(?name 'aldIncoming ?prompt "Incoming branches" ?value "")
    incoming->enabled=activeStamp==""
    rows=hiCreateReportField(?name 'aldSessions ?title "SUSPENDED MERGES" ?selectMode 'single
      ?headers '(("Session" 245 left string nil) ("Phase" 100 left string nil) ("Target" 220 left string nil)) ?choices sessions)
    start=hiCreateButton(?name 'aldStart ?buttonText "Start merge" ?callback
      "ALDMergeSetupForm->aldInfo->value=\"Loading: preparing isolated Git merge...\" ALDGUIEnqueue(list(\"merge-repository\" \"start\" \"\" ALDMergeSetupForm->aldIncoming->value))")
    start->enabled=activeStamp==""
    active=hiCreateButton(?name 'aldActive ?buttonText "Resolve active Git merge" ?enabled activeEnabled ?callback
      sprintf(nil "ALDMergeSetupForm->aldInfo->value=\"Loading: reading active Git merge...\" ALDGUIEnqueue(list(\"merge-repository\" \"active\" \"\" %L))" activeStamp))
    resume=hiCreateButton(?name 'aldResume ?buttonText "Resume selected" ?callback
      "when(ALDMergeRow(ALDMergeSetupForm->aldSessions) ALDGUIEnqueue(list(\"merge-repository\" \"resume\" ALDMergeRow(ALDMergeSetupForm->aldSessions) \"\")))")
    form=hiCreateAppForm(?name 'ALDMergeSetupForm ?formTitle "Layout Diff - Merge branches"
      ?fields list(list(info 10:10 700:190 0) list(active 10:210 700:32)
        list(hiCreateSeparatorField(?name 'aldSeparator) 10:252 700:0)
        list(incoming 10:265 700:28 150) list(rows 10:305 700:180 0)
        list(start 10:495 330:32) list(resume 360:495 350:32))
      ?buttonLayout 'Close ?dontBlock t ?dialogStyle 'modeless ?initialSize list(730 590))
    hiDisplayForm(form)))

procedure(ALDMergeRepository(token text cells files @optional stamp active (phase "resolving"))
  let((summary rows conflicts choice message fields button form n)
    unless(boundp('ALDMergeRepositoryForm) && ALDMergeRepositoryForm
      summary=hiCreateMLTextField(?name 'aldSummary ?prompt "" ?editable nil ?hasHorizontalScrollbar nil ?enableWordWrap t)
      rows=hiCreateReportField(?name 'aldCells ?title "AFFECTED CELLS" ?selectMode 'single
        ?headers '(("ID" 0 left string nil) ("Cellview" 470 left string nil) ("State" 140 left string nil)) ?choices nil)
      conflicts=hiCreateReportField(?name 'aldFiles ?title "ORDINARY FILE CONFLICTS" ?selectMode 'single
        ?headers '(("Path" 470 left string nil) ("Choice" 140 left string nil)) ?choices nil)
      choice=hiCreateCyclicField(?name 'aldFileSide ?prompt "File alternative" ?choices list("target" "incoming" "base"))
      message=hiCreateStringField(?name 'aldMessage ?prompt "Commit message" ?value "Merge layout branches")
      fields=list(list(summary 10:10 760:130 0) list(rows 10:150 760:180 0)
        list(conflicts 10:380 760:140 0) list(choice 10:530 440:28 130) list(message 10:620 760:28 130))
      button=hiCreateButton(?name 'aldOpenCell ?buttonText "Open selected cell in merge editor" ?callback
        "when(ALDMergeRow(ALDMergeRepositoryForm->aldCells) ALDMergeRepoRequest(\"open-cell\" ALDMergeRow(ALDMergeRepositoryForm->aldCells)))")
      fields=append(fields list(list(button 10:340 460:30)))
      foreach(pair '(("< Cells" "cells-previous" 480 340) ("Cells >" "cells-next" 630 340)
          ("< Files" "files-previous" 480 570) ("Files >" "files-next" 630 570)
          ("All affected paths" "paths" 10 570))
        button=hiCreateButton(?name concat("aldRepo" cadr(pair)) ?buttonText car(pair)
          ?callback sprintf(nil "ALDMergeRepoRequest(%L)" cadr(pair)))
        fields=append(fields list(list(button list(caddr(pair) cadddr(pair)) list(140 30)))))
      button=hiCreateButton(?name 'aldChooseFile ?buttonText "Accept file alternative" ?callback
        "when(ALDMergeRow(ALDMergeRepositoryForm->aldFiles) ALDMergeRepoRequest(\"file\" list(ALDMergeRow(ALDMergeRepositoryForm->aldFiles) ALDMergeRepositoryForm->aldFileSide->value)))")
      fields=append(fields list(list(button 470:530 300:30)))
      button=hiCreateButton(?name 'aldInspectFile ?buttonText "Inspect selected file diff" ?callback
        "when(ALDMergeRow(ALDMergeRepositoryForm->aldFiles) ALDMergeRepoRequest(\"show-file\" ALDMergeRow(ALDMergeRepositoryForm->aldFiles)))")
      fields=append(fields list(list(button 170:570 280:30)))
      n=0
      foreach(pair '(("Commit step" "commit") ("Publish to target" "publish") ("Refresh" "refresh"))
        button=hiCreateButton(?name concat("aldRepo" cadr(pair)) ?buttonText car(pair)
          ?callback sprintf(nil "ALDMergeRepoRequest(%L ALDMergeRepositoryForm->aldMessage->value)" cadr(pair)))
        fields=append(fields list(list(button list(10+255*n 670) list(245 32)))) n=n+1)
      button=hiCreateButton(?name 'aldDiscard ?buttonText "Discard this merge..." ?callback
        "ALDMergeDiscard(ALDMergeRepositoryForm->aldToken)")
      fields=append(fields list(list(button 10:712 760:30)))
      form=hiCreateAppForm(?name 'ALDMergeRepositoryForm ?formTitle "Layout Diff - Merge repository"
        ?fields fields ?buttonLayout 'Close ?dontBlock t ?dialogStyle 'modeless ?initialSize list(790 800)))
    ALDMergeRepositoryForm->aldStamp=stamp
    ALDMergeRepositoryForm->aldActive=active
    ALDMergeRepositoryForm->aldRepocommit->buttonText=if(active then "Stage layout resolutions" else "Commit step")
    ALDMergeRepositoryForm->aldRepocommit->enabled=phase=="resolving"
    ALDMergeRepositoryForm->aldOpenCell->enabled=phase=="resolving"
    ALDMergeRepositoryForm->aldRepopublish->enabled=!active && phase=="ready"
    ALDMergeRepositoryForm->aldChooseFile->enabled=!active && phase=="resolving"
    ALDMergeRepositoryForm->aldFileSide->enabled=!active
    ALDMergeRepositoryForm->aldMessage->enabled=!active
    ALDMergeRepositoryForm->aldDiscard->enabled=!member(phase '("published" "staged" "cancelled"))
    ALDMergeRepositoryForm->aldDiscard->buttonText=if(active then "Discard editor session..." else "Discard this merge...")
    ALDMergeRepositoryForm->aldToken=token ALDMergeRepositoryForm->aldSummary->value=text
    ALDMergeRepositoryForm->aldCells->choices=cells ALDMergeRepositoryForm->aldFiles->choices=files
    hiDisplayForm(ALDMergeRepositoryForm)))

procedure(ALDMergeDiscard(token)
  let((body yes no form)
    when(boundp('ALDMergeDiscardForm) && ALDMergeDiscardForm
      hiFormCancel(ALDMergeDiscardForm) hiDeleteForm(ALDMergeDiscardForm))
    body=hiCreateMLTextField(?name 'aldText ?prompt "" ?editable nil
      ?value "Discard this editor's preparation worktree and close its temporary views? Accepted decision journals remain for inspection. This does not abort an active Git merge or discard already staged files. The source branch and OA layouts are unchanged. Close this dialog to keep the editor session suspended.")
    yes=hiCreateButton(?name 'aldYes ?buttonText "Discard merge" ?callback sprintf(nil
      "hiFormCancel(ALDMergeDiscardForm) ALDGUIEnqueue(list(\"merge-repository\" \"cancel\" %L \"\"))" token))
    no=hiCreateButton(?name 'aldNo ?buttonText "Keep suspended" ?callback "hiFormCancel(ALDMergeDiscardForm)")
    form=hiCreateAppForm(?name 'ALDMergeDiscardForm ?formTitle "Discard unpublished merge"
      ?fields list(list(body 10:10 600:120 0) list(no 10:145 280:32) list(yes 310:145 300:32))
      ?buttonLayout 'Empty ?dontBlock t ?dialogStyle 'modeless ?initialSize list(630 220))
    hiDisplayForm(form)))

procedure(ALDMergeRepositoryOmissions(token phase text @optional active)
  let((body yes no form)
    when(boundp('ALDMergeRepoConsent) && ALDMergeRepoConsent
      hiFormCancel(ALDMergeRepoConsent) hiDeleteForm(ALDMergeRepoConsent))
    body=hiCreateMLTextField(?name 'aldWarning ?prompt "" ?editable nil ?value text)
    yes=hiCreateButton(?name 'aldYes ?buttonText if(phase==1 then "Continue" else if(active then "Confirm loss and stage" else "Confirm loss and commit"))
      ?callback sprintf(nil "hiFormCancel(ALDMergeRepoConsent) ALDGUIEnqueue(list(\"merge-repository\" %L %L \"\"))"
        if(phase==1 then "omit-continue" else "omit-confirm") token))
    no=hiCreateButton(?name 'aldNo ?buttonText "Reject" ?callback sprintf(nil
      "hiFormCancel(ALDMergeRepoConsent) ALDGUIEnqueue(list(\"merge-repository\" \"omit-cancel\" %L \"\"))" token))
    form=hiCreateAppForm(?name 'ALDMergeRepoConsent ?formTitle "Incomplete merge checkpoint"
      ?fields list(list(body 10:10 600:150 0) list(no 10:175 200:32) list(yes 230:175 380:32))
      ?buttonLayout 'Empty ?dontBlock t ?dialogStyle 'modeless ?initialSize list(630 240))
    hiDisplayForm(form)))
