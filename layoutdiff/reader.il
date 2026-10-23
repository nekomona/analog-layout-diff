; Versioned data-only snapshot adapter. Sources are opened read-only and never saved.
; Attribute/function sources: evidence/docs, Virtuoso IC23.1 installed manuals.
procedure(ALDValue(v)
  cond((null(v) nil)
       (floatp(v) list("@float" sprintf(nil "%.17g" v)))
       (listp(v) list("@list" mapcar('ALDValue v)))
       (dbobjectp(v) list("@unsupported-db-reference" v~>objType))
       (t v)))

procedure(ALDProps(o)
  foreach(mapcar p o~>prop
    list(p~>name p~>valueType
      if(p~>valueType == "hierProp" then ALDProps(p) else ALDValue(p~>value)))))

procedure(ALDScale(v dbu)
  cond((null(v) nil)
       (listp(v) foreach(mapcar x v ALDScale(x dbu)))
       (numberp(v) if(abs(v*dbu-round(v*dbu)) < 0.00001 then round(v*dbu)
                    else list("@off-grid" sprintf(nil "%.17g" v))))
       (t v)))

procedure(ALDFields(o names dimensions dbu)
  foreach(mapcar name names
    list(name if(member(name dimensions) then ALDScale(dbGet(o name) dbu)
      else ALDValue(dbGet(o name))))))

; Capture-local integer references never persist in canonical snapshots.
; These helpers share ALDRead's dynamic .il bindings, like the replay helpers.
procedure(ALDLocalRef(o)
  when(o && aldCaptureRefs
    unless(aldCaptureRefs[o] aldNextRef=aldNextRef+1 aldCaptureRefs[o]=aldNextRef)
    aldCaptureRefs[o]))

procedure(ALDEmit(port kind fields @optional obj)
  fprintf(port "%L\n" cons(list("kind" kind)
    append(fields when(obj && aldCaptureRefs list(list("_captureId" ALDLocalRef(obj))))))))

; Diagnostic content for unsupported objects. References have semantic hints,
; never process-local dbIds. This is intentionally NOT a reconstruction codec.
procedure(ALDOpaque(v)
  cond((dbobjectp(v)
         list("@diagnostic-ref" v~>objType
           when(member('name v~>?) v~>name)
           when(member('bBox v~>?) ALDValue(v~>bBox))))
       (listp(v) foreach(mapcar x v ALDOpaque(x)))
       (t ALDValue(v))))

procedure(ALDOpaqueObject(o)
  foreach(mapcar attr o~>?
    list(sprintf(nil "%s" attr) ALDOpaque(dbGet(o attr)))))

procedure(ALDGroupFields(o groupOrders)
  append(list(list("group" o~>figGroup~>name))
    when(o~>figGroup~>ordered list(list("groupOrder" groupOrders[o])))))

procedure(ALDFigure(o dbu groupOrders)
  let((pin)
    pin=o~>pin
    append(append(ALDGroupFields(o groupOrders) list(list("props" ALDProps(o)) list("net" o~>net~>name)
      list("pin" when(pin append(when(aldCaptureRefs list(list("_captureId" ALDLocalRef(pin)))) list(list("name" pin~>name) list("term" pin~>term~>name)
        list("accessDir" pin~>accessDir) list("type" pin~>type)
        list("props" ALDProps(pin)) list("primary" o==pin~>fig) list("figureCount" length(pin~>figs))))))))
      ALDFields(o '("layerName" "purpose" "routeStatus") nil dbu))))

procedure(ALDRead(lib cell view path)
  let((cv port dbu fields dims kind master attrs vals ignored custom groupOrders index aldCaptureRefs aldNextRef)
    cv=dbOpenCellViewByType(lib cell view "maskLayout" "r")
    unless(cv error("Cannot open source layout read-only"))
    unwindProtect(progn(
      port=outfile(path)
      unless(port error("Cannot open snapshot output"))
      dbu=cv~>DBUPerUU
      ; User-approved capture scope (docs/OA_OBJECT_FINDINGS.md): omit these
      ; objects and their group links, but retain member shapes/vias and nets.
      ; Key by actual collection membership so Steiner variants are covered.
      ignored=makeTable('aldIgnored nil)
      foreach(attr '("routes" "markers" "steiners")
        foreach(o dbGet(cv attr) ignored[o]=t))
      aldCaptureRefs=when(cv~>groups makeTable('aldCaptureRefs nil)) aldNextRef=0
      ; Build once, O(members), rather than searching each group's list per figure.
      ; dbIds are only temporary lookup keys and never leave this process.
      groupOrders=makeTable('aldGroupOrders nil)
      foreach(g cv~>figGroups
        when(g~>ordered
          index=0
          foreach(fig g~>figs
            unless(ignored[fig] groupOrders[fig]=index index=index+1))))
      ALDEmit(port "cell" list(list("name" "") list("dbu" round(dbu))
        list("technology" techGetTechLibName(ddGetObj(lib)))
        list("units" cv~>userUnits) list("cellType" cv~>cellType)
        list("props" ALDProps(cv))) cv)
      foreach(o setof(fig cv~>shapes !ignored[fig])
        kind=o~>objType
        fields=case(kind
          ("rect" '("bBox")) ("ellipse" '("bBox"))
          ("donut" '("xy" "innerRadius" "outerRadius"))
          ("arc" '("ellipseBBox" "bBox" "startAngle" "stopAngle"))
          ("polygon" '("points")) ("line" '("points"))
          ("path" '("points" "width" "pathStyle" "beginExt" "endExt"))
          ("pathSeg" '("beginPt" "endPt" "width" "beginStyle" "endStyle" "beginExt" "endExt" "topology"))
          ("label" '("xy" "theLabel" "justify" "orient" "font" "height" "isDrafted" "isOverbar" "isVisible" "labelType"))
          (t '("bBox")))
        dims='("bBox" "points" "xy" "width" "height" "beginPt" "endPt" "beginExt" "endExt" "ellipseBBox" "innerRadius" "outerRadius")
        ; IC23.1 dbGetPathSegStyle returns (width beginStyle endStyle
        ;   (beginExt endExt (beginLeftDiagExt beginRightDiagExt beginRightHalfWidth
        ;                        endLeftDiagExt endRightDiagExt endRightHalfWidth))).
        ; Preserve its API units directly: diagonal dimensions are not Euclidean
        ; lengths and must not be rescaled by sqrt(2) on replay.
        custom=when(kind=="pathSeg" && member("custom" list(o~>beginStyle o~>endStyle))
          list(list("customExtensions" ALDScale(caddr(nth(3 dbGetPathSegStyle(o))) dbu))))
        ALDEmit(port kind append(append(append(ALDFigure(o dbu groupOrders) ALDFields(o fields dims dbu)) custom)
          unless(member(kind '("rect" "ellipse" "polygon" "line" "path" "pathSeg" "label" "donut" "arc"))
            list(list("diagnosticAttributes" ALDOpaqueObject(o))))) o))
      foreach(o cv~>nets
        ALDEmit(port "net" append(list(list("props" ALDProps(o)))
          ALDFields(o '("name" "sigType" "isGlobal" "numBits" "connStatus" "criticality" "routePattern" "source") nil dbu)) o))
      foreach(o cv~>terminals
        ALDEmit(port "term" append(list(list("props" ALDProps(o)) list("net" o~>net~>name))
          ALDFields(o '("name" "direction") nil dbu)) o)
        foreach(p o~>pins
          unless(p~>fig ALDEmit(port "unsupported" list(list("category" "pin-without-figure") list("term" o~>name))))))
      foreach(o setof(i cv~>instances i~>objType == "inst")
        master=o~>master
        ALDEmit(port "inst" append(append(ALDGroupFields(o groupOrders) list(list("props" ALDProps(o))
          list("pcell" if(master~>superMaster then t else nil))
          list("params" when(master~>superMaster
            foreach(mapcar p master~>parameters~>value list(p~>name p~>valueType ALDValue(p~>value)))))
          list("connections" foreach(mapcar it o~>instTerms append(list(it~>name it~>net~>name ALDProps(it)) when(aldCaptureRefs list(ALDLocalRef(it))))))))
          ALDFields(o '("name" "libName" "cellName" "viewName" "xy" "orient" "numInst" "physOnly" "status" "source") '("xy") dbu)) o))
      foreach(o cv~>mosaics
        master=o~>master
        ALDEmit(port "mosaic" append(append(when(o~>figGroup ALDGroupFields(o groupOrders)) list(list("props" ALDProps(o))
          list("params" when(master~>superMaster
            foreach(mapcar p master~>parameters~>value list(p~>name p~>valueType ALDValue(p~>value)))))))
          ALDFields(o '("name" "libName" "cellName" "viewName" "xy" "orient" "rows" "columns" "uX" "uY" "tileArray" "mosaicType") '("xy" "uX" "uY") dbu)) o))
      foreach(o cv~>vias
        ALDEmit(port o~>objType append(append(ALDGroupFields(o groupOrders) list(list("props" ALDProps(o)) list("net" o~>net~>name)
          list("viaDef" o~>viaHeader~>viaDefName)
          list("params" ALDValue(o~>viaHeader~>overrideParams))))
          ALDFields(o '("origin" "orient" "purpose" "routeStatus") '("origin") dbu)) o))
      foreach(o cv~>figGroups
        ALDEmit(port "figGroup" append(append(list(list("props" ALDProps(o)))
          append(when(o~>figGroup ALDGroupFields(o groupOrders))
            when(o~>ordered list(list("memberCount" length(setof(fig o~>figs !ignored[fig])))))))
          ALDFields(o '("name" "origin" "orient" "ordered" "type") '("origin") dbu)) o))
      foreach(o cv~>groups
        ALDEmit(port "group" append(list(list("props" ALDProps(o))
          list("_members" foreach(mapcar gm setof(member o~>members !ignored[member~>object])
            list(ALDLocalRef(gm~>object) gm~>object~>objType ALDProps(gm)))))
          ALDFields(o '("name" "defName" "isSet" "isCollection" "isOrdered" "isUniqueName" "deleteWhen") nil dbu)) o))
      when(cv~>prBoundary
        o=cv~>prBoundary
        ALDEmit(port "prBoundary" append(list(list("props" ALDProps(o)))
          ALDFields(o '("points") '("points") dbu)) o))
      ; Other nonempty unimplemented collections remain blockers.
      foreach(attr '("blockages" "areaBoundaries" "snapBoundary"
          "guides" "rows" "trackPatterns" "gCellPatterns" "sitePattern" "clusters"
          "textDisplays" "assocTextDisplays" "widthSpacingSnapPatternDefs")
        vals=dbGet(cv attr)
        when(vals
          foreach(o if(listp(vals) then vals else list(vals))
            ALDEmit(port "unsupported" append(
              when(dbobjectp(o) && member('figGroup o~>?) && o~>figGroup ALDGroupFields(o groupOrders))
              list(list("category" attr)
                list("diagnosticAttributes" if(dbobjectp(o) then ALDOpaqueObject(o) else ALDOpaque(o))))) o))))
      t)
      progn(when(port close(port)) dbClose(cv)))))
