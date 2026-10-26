; Native Git-style history browser. Selection callbacks only queue data requests.
when(boundp('ALDGUIHistoryForm) && ALDGUIHistoryForm
  hiFormCancel(ALDGUIHistoryForm) hiDeleteForm(ALDGUIHistoryForm) ALDGUIHistoryForm=nil)

procedure(ALDGUIBrowserClosed(form)
  form->aldOpen=nil
  when(form->aldBrowserToken && ALDGUIOwner && (!boundp('ALDRuntimeState) || ALDRuntimeState=="Running")
    ALDGUIEnqueue(list("browser-close" form->aldBrowserToken))))

procedure(ALDGUIBrowserCreate()
  let((sources commits files categories pager summary patch repo status toolbar main lower body tabs refs graph cells buttons previous next pageLabel title fields x widths)
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
      refs=hiCreateReportField(?name 'aldRefs ?title "BRANCHES / TAGS" ?selectMode 'browse
        ?headers '(("Ref" 180 left string nil)) ?choices nil
        ?callback "ALDGUIRepositoryRef(ALDGUIHistoryForm)")
      graph=hiCreateReportField(?name 'aldGraph ?title "GIT COMMIT GRAPH" ?selectMode 'browse
        ?headers '(("Graph / revision" 140 left string nil) ("Message" 240 left string nil)
          ("Author" 90 left string nil) ("Date" 140 left string nil) ("Refs" 200 left string nil))
        ?choices nil ?altRowHilight t ?callback "ALDGUIRepositorySelect(ALDGUIHistoryForm)")
      cells=hiCreateReportField(?name 'aldChangedCells ?title "CELLS MODIFIED IN COMMIT" ?selectMode 'browse
        ?headers '(("Cell" 150 left string nil) ("Library" 120 left string nil) ("View" 60 left string nil))
        ?choices nil ?altRowHilight t ?callback "ALDGUIRepositoryCell(ALDGUIHistoryForm)")
      tabs=hiCreateTabField(?name 'aldViews ?tabs list("Cell-centric" "Git-centric") ?tabPlacement 'top
        ?fields list(list(list(sources 8:8 230:230 0) list(commits 248:8 980:230 0))
          list(list(refs 8:8 200:230 0) list(graph 218:8 660:230 0) list(cells 888:8 340:230 0)))
        ?callback "ALDGUIBrowserTab(ALDGUIHistoryForm)")
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
      previous=hiCreateButton(?name 'aldPrevious ?buttonText "Previous" ?enabled nil
        ?callback "ALDGUIBrowserTurnPage(ALDGUIHistoryForm -1)")
      pageLabel=hiCreateStringField(?name 'aldPageLabel ?prompt "" ?editable nil ?value "Select a category for details")
      next=hiCreateButton(?name 'aldNext ?buttonText "Next" ?enabled nil
        ?callback "ALDGUIBrowserTurnPage(ALDGUIHistoryForm 1)")
      status=hiCreateStringField(?name 'aldBrowserStatus ?prompt "" ?editable nil ?value "Select a layout to browse its history.")
      buttons=list(
        hiCreateButton(?name 'aldRefresh ?buttonText "Refresh" ?callback "ALDGUIBrowserRefresh(ALDGUIHistoryForm)")
        hiCreateButton(?name 'aldSave ?buttonText "Save && Commit" ?callback "ALDGUIBrowserSave(ALDGUIHistoryForm)")
        hiCreateButton(?name 'aldReview ?buttonText "Review layout" ?enabled nil ?callback "ALDGUIHistoryCB(ALDGUIHistoryForm)")
        hiCreateButton(?name 'aldRestore ?buttonText "Restore checkpoint..." ?enabled nil ?callback "ALDGUIBrowserRestore(ALDGUIHistoryForm)")
        hiCreateButton(?name 'aldSemantic ?buttonText "All categories" ?enabled nil ?callback "ALDGUIBrowserSemantic(ALDGUIHistoryForm)")
        hiCreateButton(?name 'aldFull ?buttonText "Open full diff" ?enabled nil ?callback "ALDGUIBrowserFull(ALDGUIHistoryForm)")
        hiCreateButton(?name 'aldMore ?buttonText "More commits" ?callback "ALDGUIRepositoryMore(ALDGUIHistoryForm)")
        hiCreateButton(?name 'aldRuntime ?buttonText "Runtime..." ?callback "ALDRuntimePanel()"))
      title=hiCreateStringField(?name 'aldDiffTitle ?prompt "" ?editable nil ?value "All change categories")
      fields=list(list(repo 10:8 1250:24 0) list(tabs 10:78 1250:275 0)
        list(summary 10:363 1250:105 0) list(files 10:478 390:350 0)
        list(categories 412:478 848:166 0) list(previous 412:654 120:28)
        list(pageLabel 540:654 592:28 0) list(next 1140:654 120:28)
        list(title 412:691 848:25 0) list(patch 412:724 848:104 0)
        list(status 10:838 1250:24 0))
      x=10 widths=list(75 135 115 160 120 130 120 115)
      foreach(button buttons
        fields=append(fields list(list(button list(x 40) list(car(widths) 28))))
        x=x+car(widths)+8 widths=cdr(widths))
      ALDGUIHistoryForm=hiCreateAppForm(?name 'ALDGUIHistoryForm ?formTitle "Layout Diff - Git History & Changes"
        ?fields fields ?initialSize list(1280 930) ?minSize list(1280 930) ?buttonLayout 'Close
        ?callback 'ALDGUIBrowserClosed ?dontBlock t ?dialogStyle 'modeless)
      hiInstantiateForm(ALDGUIHistoryForm))
    ALDGUIHistoryForm))

procedure(ALDGUIBrowserClear(form)
  form->aldSelectedCommit=nil form->aldPath=nil form->aldSelectedFile=-1
  form->aldSelectedCategory=-1 form->aldCategoryPage=0 form->aldCategoryPages=0
  form->aldCategories->choices=nil
  form->aldPrevious->enabled=nil form->aldNext->enabled=nil
  form->aldPageLabel->value="Select a category for details"
  form->aldFiles->choices=nil form->aldSummary->value=""
  form->aldPatch->value="Select a commit to inspect its changes."
  form->aldReview->enabled=nil form->aldRestore->enabled=nil form->aldSemantic->enabled=nil form->aldFull->enabled=nil)

procedure(ALDGUIBrowserLoad(token identity sources sourceIndex repository rows ids)
  let((form)
    form=ALDGUIBrowserCreate() form->aldLoading=t
    form->aldViews->value=1 form->aldMore->enabled=nil
    form->aldBrowserToken=token form->aldSource=identity form->aldSources=sources form->aldIds=ids
    form->aldRepository->value=repository
    form->aldViews->page1->aldLayouts->choices=foreach(mapcar item sources list(cadr(item) car(item) caddr(item)))
    when(sources hiReportSelectItem(form->aldViews->page1->aldLayouts sourceIndex nil))
    form->aldViews->page1->aldCommits->choices=rows ALDGUIBrowserClear(form)
    if(rows then
      hiReportSelectItem(form->aldViews->page1->aldCommits 0 nil) form->aldSelectedCommit=car(ids)
      form->aldPatch->value="Loading commit..."
    else form->aldPatch->value="No recorded commits for this layout. Use Save & Commit from an editable source layout.")
    ALDGUIBrowserSetStatus(form sprintf(nil "%d revisions | A added, M modified, D deleted, MN modified net. M excludes MN. Full diffs and snapshots retain all fields." length(ids)))
    form->aldLoading=nil form->aldOpen=t
    hiDisplayForm(form)))

procedure(ALDGUIBrowserSelection(form)
  let((index)
    unless(form->aldLoading
      index=car(form->aldViews->page1->aldCommits->value)
      when(index
        ALDGUIBrowserClear(form) form->aldSelectedCommit=nth(index form->aldIds)
        form->aldPatch->value="Loading commit..."
        ALDGUIEnqueue(list("browser-select" form->aldBrowserToken form->aldSelectedCommit))))))

procedure(ALDGUIBrowserSource(form)
  let((index)
    unless(form->aldLoading
      index=car(form->aldViews->page1->aldLayouts->value)
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
      form->aldReview->enabled=t form->aldRestore->enabled=t form->aldSemantic->enabled=t form->aldFull->enabled=t)))

procedure(ALDGUIBrowserCounts(token commitId rows)
  let((form index)
    form=ALDGUIHistoryForm
    when(form && form->aldBrowserToken==token && form->aldSelectedCommit==commitId
      form->aldLoading=t
      index=car(form->aldViews->page1->aldCommits->value)
      form->aldViews->page1->aldCommits->choices=rows
      when(index hiReportSelectItem(form->aldViews->page1->aldCommits index nil))
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
  when(form->aldBrowserToken && form->aldSource && form->aldSelectedCommit
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
      form->aldFullWindow=ALDGUIViewFile(path "Layout Diff - Complete Change Details"))))

procedure(ALDGUIBrowserRefresh(form)
  form->aldBrowserToken=nil ALDGUIBrowserClear(form)
  if(form->aldViews->value==2 then ALDGUIEnqueue(list("repository" 0 500))
  else ALDGUIEnqueue(append(list("browser") form->aldSource))))

procedure(ALDGUIBrowserRefreshIfOpen(identity)
  when(boundp('ALDGUIHistoryForm) && ALDGUIHistoryForm && ALDGUIHistoryForm->aldOpen
    ALDGUIHistoryForm->aldSource=identity ALDGUIBrowserRefresh(ALDGUIHistoryForm)))

procedure(ALDGUIBrowserSave(form)
  when(form->aldSource ALDGUIQuickSaveIdentity(form->aldSource)))

procedure(ALDGUIBrowserRestore(form)
  when(form->aldSource && form->aldSelectedCommit && form->aldRestore->enabled
    ALDGUIEnqueue(append(list("restore-prepare") append(form->aldSource list(form->aldSelectedCommit))))))

procedure(ALDGUIBrowserTab(form)
  unless(form->aldLoading ALDGUIBrowserRefresh(form)))

procedure(ALDGUIRepositoryLoad(token repository refs refIndex rows ids limit)
  let((form)
    form=ALDGUIBrowserCreate() form->aldLoading=t form->aldViews->value=2
    form->aldBrowserToken=token form->aldSource=nil form->aldRepository->value=repository
    form->aldGitIds=ids form->aldGitLimit=limit form->aldRefIndex=refIndex
    form->aldViews->page2->aldRefs->choices=foreach(mapcar ref refs list(ref))
    when(refs hiReportSelectItem(form->aldViews->page2->aldRefs refIndex nil))
    form->aldViews->page2->aldGraph->choices=rows form->aldViews->page2->aldChangedCells->choices=nil ALDGUIBrowserClear(form)
    when(ids hiReportSelectItem(form->aldViews->page2->aldGraph 0 nil) form->aldSelectedCommit=car(ids))
    form->aldMore->enabled=length(ids)>=limit
    ALDGUIBrowserSetStatus(form sprintf(nil "%d commits shown. Select a commit, then a changed cell. Merge changes compare with the first parent." length(ids)))
    form->aldLoading=nil form->aldOpen=t hiDisplayForm(form)))

procedure(ALDGUIRepositoryRef(form)
  let((index) unless(form->aldLoading
    index=car(form->aldViews->page2->aldRefs->value)
    when(index ALDGUIBrowserClear(form) form->aldBrowserToken=nil
      ALDGUIEnqueue(list("repository" index 500))))))

procedure(ALDGUIRepositoryMore(form)
  when(form->aldViews->value==2
    ALDGUIEnqueue(list("repository" form->aldRefIndex form->aldGitLimit+500))))

procedure(ALDGUIRepositorySelect(form)
  let((index) unless(form->aldLoading
    index=car(form->aldViews->page2->aldGraph->value)
    when(index ALDGUIBrowserClear(form) form->aldSource=nil form->aldViews->page2->aldChangedCells->choices=nil
      form->aldSelectedCommit=nth(index form->aldGitIds)
      ALDGUIEnqueue(list("repository-select" form->aldBrowserToken form->aldSelectedCommit))))))

procedure(ALDGUIRepositoryCells(token revision identities)
  let((form) form=ALDGUIHistoryForm
    when(form && form->aldBrowserToken==token && form->aldSelectedCommit==revision
      form->aldLoading=t form->aldGitCells=identities
      form->aldViews->page2->aldChangedCells->choices=foreach(mapcar item identities list(cadr(item) car(item) caddr(item)))
      if(identities then hiReportSelectItem(form->aldViews->page2->aldChangedCells 0 nil)
      else form->aldSummary->value="This commit changes no recorded layout cells." form->aldSource=nil)
      form->aldLoading=nil)))

procedure(ALDGUIRepositoryCell(form)
  let((index revision) unless(form->aldLoading
    index=car(form->aldViews->page2->aldChangedCells->value) revision=form->aldSelectedCommit
    when(index && revision ALDGUIBrowserClear(form) form->aldSelectedCommit=revision
      ALDGUIEnqueue(list("repository-cell" form->aldBrowserToken revision index))))))
