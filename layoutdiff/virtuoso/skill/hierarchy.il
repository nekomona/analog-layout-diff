; Read-only hierarchy metadata. Never serialize child shapes or save a child.
; IC23.1 sources: Cellview Attributes, ddGetObjReadPath, dbIsCellViewModified.
procedure(ALDDependencyInfo(master lib cell view)
  let((persistent dd)
    persistent=when(master if(master~>superMaster then master~>superMaster else master))
    dd=ddGetObj(lib cell view)
    list(list("libName" lib) list("cellName" cell) list("viewName" view)
      list("path" when(dd ddGetObjReadPath(dd)))
      list("resolved" if(master then t else nil))
      list("pcell" when(persistent persistent~>isParamCell))
      list("savedTime" when(persistent persistent~>fileTimeStamp))
      list("dirty" when(persistent dbIsCellViewModified(persistent)))
      list("dirtyCounter" when(persistent
        when(dbIsCellViewModified(persistent) persistent~>modifiedCounter))))))

procedure(ALDDependencies(lib cell view path)
  let((cv port queue seen m o)
    cv=dbOpenCellViewByType(lib cell view "maskLayout" "r")
    unless(cv error("Cannot open hierarchy root read-only"))
    unwindProtect(progn(
      port=outfile(path)
      unless(port error("Cannot open hierarchy metadata output"))
      seen=makeTable('aldHierarchySeen nil)
      queue=list(cv)
      while(queue
        m=car(queue) queue=cdr(queue)
        unless(seen[m]
          seen[m]=t
          foreach(o append(setof(i m~>instances i~>objType == "inst") m~>mosaics)
            ; dbIds only guard traversal; persistent identities are lib/cell/view.
            fprintf(port "%L\n" ALDDependencyInfo(o~>master o~>libName o~>cellName o~>viewName))
            when(o~>master queue=cons(o~>master queue)))))
      t)
      progn(when(port close(port)) dbClose(cv)))))

procedure(ALDCheckDependencies(identities path)
  let((cv port lib cell view)
    unwindProtect(progn(
      port=outfile(path)
      unless(port error("Cannot open dependency check output"))
      foreach(identity identities
        lib=car(identity) cell=cadr(identity) view=caddr(identity)
        cv=when(ddGetObj(lib cell view) dbOpenCellViewByType(lib cell view "maskLayout" "r"))
        fprintf(port "%L\n" ALDDependencyInfo(cv lib cell view))
        when(cv dbClose(cv) cv=nil))
      t)
      progn(when(cv dbClose(cv)) when(port close(port))))))
