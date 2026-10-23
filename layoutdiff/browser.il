; Native Git-style history browser. Selection callbacks only queue data requests.
when(boundp('ALDGUIHistoryForm) && ALDGUIHistoryForm
  hiFormCancel(ALDGUIHistoryForm) hiDeleteForm(ALDGUIHistoryForm))

procedure(ALDGUIBrowserClosed(form) form->aldOpen=nil)

procedure(ALDGUIBrowserCreate()
  let((sources commits files categories pager summary patch repo status toolbar main lower body)
    unless(boundp('ALDGUIHistoryForm) && ALDGUIHistoryForm
      repo=hiCreateStringField(?name 'aldRepository ?prompt "" ?editable nil)
      sources=hiCreateReportField(?name 'aldLayouts ?title "LAYOUTS" ?selectMode 'browse
        ?headers '(("Cell" 160 left string nil) ("Library" 70 left string nil) ("View" 0 left string nil))
        ?choices nil ?altRowHilight t ?callback "ALDGUIBrowserSource(ALDGUIHistoryForm)")
      commits=hiCreateReportField(?name 'aldCommits ?title "GIT HISTORY / SELECTED LAYOUT" ?selectMode 'browse
        ?headers '(("Revision" 95 left string nil) ("Message" 285 left string nil)
          ("Author" 90 left string nil) ("Date" 145 left string nil)
          ("+ Objects" 65 right string nil) ("~ Objects" 65 right string nil) ("- Objects" 65 right string nil)
          ("Modified net" 90 right string nil))
        ?choices nil ?altRowHilight t ?callback "ALDGUIBrowserSelection(ALDGUIHistoryForm)"
        ?doubleClickCB "ALDGUIHistoryCB(ALDGUIHistoryForm)")
      files=hiCreateReportField(?name 'aldFiles ?title "AFFECTED FILES" ?selectMode 'single
        ?headers '(("Status" 40 left string nil) ("Cellview / file" 150 left string nil)
          ("+ Lines" 45 right string nil) ("- Lines" 45 right string nil))
        ?choices nil ?altRowHilight t ?callback "ALDGUIBrowserFile(ALDGUIHistoryForm)")
      summary=hiCreateMLTextField(?name 'aldSummary ?prompt "" ?editable nil
        ?hasHorizontalScrollbar nil ?enableWordWrap t)
      patch=hiCreateHypertextField(?name 'aldPatch ?hasHorizontalScrollbar t ?hasVerticalScrollbar t)
      categories=hiCreateReportField(?name 'aldCategories ?title "CHANGE CATEGORIES" ?selectMode 'single
        ?headers '(("Layer / master / category" 330 left string nil)
          ("A" 45 right int nil) ("M" 45 right int nil) ("D" 45 right int nil)
          ("Modified net" 100 right int nil))
        ?choices nil ?altRowHilight t ?callback "ALDGUIBrowserCategory(ALDGUIHistoryForm)")
      pager=hiCreateHorizontalBoxLayout('aldCategoryPager ?spacing 6 ?items list(
        hiCreateButton(?name 'aldPrevious ?buttonText "Previous" ?enabled nil
          ?callback "ALDGUIBrowserTurnPage(ALDGUIHistoryForm -1)")
        hiCreateStringField(?name 'aldPageLabel ?prompt "" ?editable nil ?value "Select a category for details")
        hiCreateButton(?name 'aldNext ?buttonText "Next" ?enabled nil
          ?callback "ALDGUIBrowserTurnPage(ALDGUIHistoryForm 1)")))
      status=hiCreateStringField(?name 'aldBrowserStatus ?prompt "" ?editable nil ?value "Select a layout to browse its history.")
      toolbar=hiCreateHorizontalBoxLayout('aldBrowserToolbar ?spacing 8 ?items list(
        hiCreateButton(?name 'aldRefresh ?buttonText "Refresh" ?callback "ALDGUIBrowserRefresh(ALDGUIHistoryForm)")
        hiCreateButton(?name 'aldSave ?buttonText "Save && Commit" ?callback "ALDGUIBrowserSave(ALDGUIHistoryForm)")
        hiCreateButton(?name 'aldReview ?buttonText "Review layout" ?enabled nil ?callback "ALDGUIHistoryCB(ALDGUIHistoryForm)")
        hiCreateButton(?name 'aldSemantic ?buttonText "All categories" ?enabled nil ?callback "ALDGUIBrowserSemantic(ALDGUIHistoryForm)")
        hiCreateButton(?name 'aldFull ?buttonText "Open full diff" ?enabled nil ?callback "ALDGUIBrowserFull(ALDGUIHistoryForm)")
        list('stretch_item 1)
        hiCreateButton(?name 'aldRuntime ?buttonText "Runtime..." ?callback "ALDRuntimePanel()")))
      lower=hiCreateHorizontalBoxLayout('aldBrowserLower ?spacing 8 ?items list(
        list(files 'stretch 1)
        list(hiCreateVerticalBoxLayout('aldDiffPanel ?frame "DIFF" ?items list(
          list(categories 'stretch 2) pager
          hiCreateStringField(?name 'aldDiffTitle ?prompt "" ?editable nil ?value "All change categories")
          list(patch 'stretch 3))) 'stretch 2)))
      main=hiCreateVerticalBoxLayout('aldBrowserMain ?spacing 8 ?items list(
        list(commits 'stretch 1) list(summary 'stretch 0) list(lower 'stretch 4)))
      body=hiCreateHorizontalBoxLayout('aldBrowserBody ?spacing 10 ?items list(
        list(sources 'stretch 1) list(main 'stretch 4)))
      ALDGUIHistoryForm=hiCreateLayoutForm('ALDGUIHistoryForm "Layout Diff - Git History & Changes"
        hiCreateVerticalBoxLayout('aldBrowserRoot ?margins '(10 10 10 10) ?spacing 8
          ?items list(repo toolbar list(body 'stretch 1) status))
        ?initialSize '(1280 880) ?minSize '(1100 780) ?buttonLayout 'Close
        ?callback 'ALDGUIBrowserClosed ?dialogStyle 'modeless)
      hiInstantiateForm(ALDGUIHistoryForm)
      hiSetFieldMinSize(ALDGUIHistoryForm 'aldLayouts ?widgetWidth 210)
      hiSetFieldMinSize(ALDGUIHistoryForm 'aldCommits ?widgetHeight 140)
      hiSetFieldMinSize(ALDGUIHistoryForm 'aldSummary ?widgetHeight 100)
      hiSetFieldMinSize(ALDGUIHistoryForm 'aldFiles ?widgetWidth 310 ?widgetHeight 240)
      hiSetFieldMinSize(ALDGUIHistoryForm 'aldCategories ?widgetHeight 180)
      hiSetFieldMinSize(ALDGUIHistoryForm 'aldPatch ?widgetWidth 410 ?widgetHeight 160))
    ALDGUIHistoryForm))

procedure(ALDGUIBrowserClear(form)
  form->aldSelectedCommit=nil form->aldPath=nil form->aldSelectedFile=-1
  form->aldSelectedCategory=-1 form->aldCategoryPage=0 form->aldCategoryPages=0
  form->aldCategories->choices=nil
  form->aldPrevious->enabled=nil form->aldNext->enabled=nil
  form->aldPageLabel->value="Select a category for details"
  form->aldFiles->choices=nil form->aldSummary->value=""
  form->aldPatch->value="Select a commit to inspect its changes."
  form->aldReview->enabled=nil form->aldSemantic->enabled=nil form->aldFull->enabled=nil)

procedure(ALDGUIBrowserLoad(token identity sources sourceIndex repository rows ids)
  let((form)
    form=ALDGUIBrowserCreate() form->aldLoading=t
    form->aldBrowserToken=token form->aldSource=identity form->aldSources=sources form->aldIds=ids
    form->aldRepository->value=repository
    form->aldLayouts->choices=foreach(mapcar item sources list(cadr(item) car(item) caddr(item)))
    when(sources hiReportSelectItem(form->aldLayouts sourceIndex nil))
    form->aldCommits->choices=rows ALDGUIBrowserClear(form)
    if(rows then
      hiReportSelectItem(form->aldCommits 0 nil) form->aldSelectedCommit=car(ids)
      form->aldPatch->value="Loading commit..."
    else form->aldPatch->value="No recorded commits for this layout. Use Save & Commit from an editable source layout.")
    form->aldBrowserStatus->value=sprintf(nil "%d revisions | A added, M modified, D deleted, MN modified net. M excludes MN. Full diffs and snapshots retain all fields." length(ids))
    form->aldLoading=nil form->aldOpen=t
    hiDisplayForm(form)))

procedure(ALDGUIBrowserSelection(form)
  let((index)
    unless(form->aldLoading
      index=car(form->aldCommits->value)
      when(index
        ALDGUIBrowserClear(form) form->aldSelectedCommit=nth(index form->aldIds)
        form->aldPatch->value="Loading commit..."
        ALDGUIEnqueue(list("browser-select" form->aldBrowserToken form->aldSelectedCommit))))))

procedure(ALDGUIBrowserSource(form)
  let((index)
    unless(form->aldLoading
      index=car(form->aldLayouts->value)
      when(index
        form->aldSource=nth(index form->aldSources) form->aldBrowserToken=nil
        ALDGUIBrowserClear(form)
        ALDGUIEnqueue(append(list("history") form->aldSource))))))

procedure(ALDGUIBrowserDetail(token commitId summary files categories patch)
  let((form)
    form=ALDGUIHistoryForm
    when(form && form->aldBrowserToken==token && form->aldSelectedCommit==commitId
      form->aldLoading=t form->aldFiles->choices=files form->aldCategories->choices=categories form->aldLoading=nil
      form->aldSummary->value=summary
      form->aldPatch->value=patch form->aldPatch->pos="aldTop" form->aldSelectedFile=-1
      form->aldDiffTitle->value="All change categories"
      form->aldReview->enabled=t form->aldSemantic->enabled=t form->aldFull->enabled=t)))

procedure(ALDGUIBrowserCounts(token commitId rows)
  let((form index)
    form=ALDGUIHistoryForm
    when(form && form->aldBrowserToken==token && form->aldSelectedCommit==commitId
      form->aldLoading=t
      index=car(form->aldCommits->value)
      form->aldCommits->choices=rows
      when(index hiReportSelectItem(form->aldCommits index nil))
      form->aldLoading=nil)))

procedure(ALDGUIBrowserFile(form)
  let((index)
    unless(form->aldLoading
      index=car(form->aldFiles->value)
      when(index && form->aldSelectedCommit
        form->aldLoading=t form->aldCategories->value=nil form->aldLoading=nil
        form->aldSelectedCategory=-1 form->aldPrevious->enabled=nil form->aldNext->enabled=nil
        form->aldPageLabel->value="Git file patch"
        form->aldSelectedFile=index form->aldFull->enabled=nil
        ALDGUIEnqueue(list("browser-file" form->aldBrowserToken form->aldSelectedCommit index))))))

procedure(ALDGUIBrowserSemantic(form)
  when(form->aldSelectedCommit
    form->aldLoading=t form->aldFiles->value=nil form->aldCategories->value=nil form->aldLoading=nil
    form->aldSelectedCategory=-1 form->aldPrevious->enabled=nil form->aldNext->enabled=nil
    form->aldPageLabel->value="Select a category for details"
    form->aldSelectedFile=-1 form->aldFull->enabled=nil
    ALDGUIEnqueue(list("browser-file" form->aldBrowserToken form->aldSelectedCommit -1))))

procedure(ALDGUIBrowserPatch(token commitId index title patch path)
  let((form)
    form=ALDGUIHistoryForm
    when(form && form->aldBrowserToken==token && form->aldSelectedCommit==commitId && form->aldSelectedFile==index
      form->aldDiffTitle->value=title form->aldPatch->value=patch form->aldPatch->pos="aldTop"
      form->aldPath=path form->aldFull->enabled=t)))

procedure(ALDGUIBrowserCategory(form)
  let((index)
    unless(form->aldLoading
      index=car(form->aldCategories->value)
      when(index && form->aldSelectedCommit
        form->aldLoading=t form->aldFiles->value=nil form->aldLoading=nil
        form->aldSelectedFile=-2 form->aldSelectedCategory=index form->aldCategoryPage=0
        form->aldPrevious->enabled=nil form->aldNext->enabled=nil form->aldFull->enabled=nil
        ALDGUIEnqueue(list("browser-category" form->aldBrowserToken form->aldSelectedCommit index 0))))))

procedure(ALDGUIBrowserTurnPage(form delta)
  let((page)
    page=form->aldCategoryPage+delta
    when(form->aldSelectedCategory>=0 && page>=0 && page<form->aldCategoryPages
      form->aldCategoryPage=page
      form->aldPrevious->enabled=nil form->aldNext->enabled=nil form->aldFull->enabled=nil
      ALDGUIEnqueue(list("browser-category" form->aldBrowserToken form->aldSelectedCommit form->aldSelectedCategory page)))))

procedure(ALDGUIBrowserCategoryData(token commitId index page title patch pages)
  let((form)
    form=ALDGUIHistoryForm
    when(form && form->aldBrowserToken==token && form->aldSelectedCommit==commitId &&
         form->aldSelectedCategory==index && form->aldCategoryPage==page
      form->aldCategoryPages=pages
      form->aldDiffTitle->value=title form->aldPatch->value=patch form->aldPatch->pos="aldTop"
      form->aldPageLabel->value=sprintf(nil "Page %d/%d (10 per page)" page+1 pages)
      form->aldPrevious->enabled=page>0 form->aldNext->enabled=page+1<pages
      form->aldFull->enabled=t)))

procedure(ALDGUIHistoryCB(form)
  ; A double-click can arrive before the queued detail request completes.
  ; Its selected revision is already fixed and review is queued after selection.
  when(form->aldBrowserToken && form->aldSelectedCommit
    ALDGUIEnqueue(append(list("review") append(form->aldSource list(form->aldSelectedCommit))))))

procedure(ALDGUIBrowserFull(form)
  when(form->aldSelectedCommit && form->aldFull->enabled
    ALDGUIEnqueue(list("browser-full" form->aldBrowserToken form->aldSelectedCommit
      form->aldSelectedFile form->aldSelectedCategory))))

procedure(ALDGUIBrowserOpenFull(token commitId fileIndex categoryIndex path)
  let((form)
    form=ALDGUIHistoryForm
    when(form && form->aldBrowserToken==token && form->aldSelectedCommit==commitId &&
         form->aldSelectedFile==fileIndex && form->aldSelectedCategory==categoryIndex
      form->aldFullWindow=hiViewTextFile(path ?title "Layout Diff - Complete Change Details" ?fixedFont t))))

procedure(ALDGUIBrowserRefresh(form)
  form->aldBrowserToken=nil ALDGUIBrowserClear(form)
  ALDGUIEnqueue(append(list("browser") form->aldSource)))

procedure(ALDGUIBrowserRefreshIfOpen(identity)
  when(boundp('ALDGUIHistoryForm) && ALDGUIHistoryForm && ALDGUIHistoryForm->aldOpen
    ALDGUIHistoryForm->aldSource=identity ALDGUIBrowserRefresh(ALDGUIHistoryForm)))

procedure(ALDGUIBrowserSave(form)
  ALDGUIQuickSaveIdentity(form->aldSource))
