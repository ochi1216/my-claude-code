Attribute VB_Name = "modSearchViewController"
Option Explicit

' 未読／すべての切替、フィルター適用、復元を担当するモジュール。
'
' 設計の要点：登録時に「このフォルダー・自分のみ」スコープの専用ビュー
' (SFVT_Managed) を元のビューから複製して作る。以後の操作は必ずこの
' 専用ビューだけに対して行い、元のビューには二度と触れない。
' そのため元のビューの共有スコープ（他フォルダーと共通かどうか）が
' 何であっても、この機能が他フォルダーへ影響することは構造的にない。

Private Function IsSearchFolder(fld As Folder) As Boolean
    On Error GoTo NotFound
    Dim searchFolders As Folders
    Set searchFolders = fld.Store.GetSearchFolders

    Dim sf As Folder
    For Each sf In searchFolders
        If sf.EntryID = fld.EntryID Then
            IsSearchFolder = True
            Exit Function
        End If
    Next sf
    IsSearchFolder = False
    Exit Function

NotFound:
    IsSearchFolder = False
End Function

Private Function CurrentExplorerFolder(expl As Explorer) As Folder
    On Error Resume Next
    Set CurrentExplorerFolder = expl.CurrentFolder
    On Error GoTo 0
End Function

' ---- 登録・解除（操作マクロから直接呼ぶ） ----

Public Sub RegisterCurrentFolder()
    Dim expl As Explorer
    Set expl = Application.ActiveExplorer
    If expl Is Nothing Then
        MsgBox "アクティブなOutlookウィンドウが見つかりません。", vbExclamation
        Exit Sub
    End If

    Dim fld As Folder
    Set fld = expl.CurrentFolder
    If fld Is Nothing Then
        MsgBox "フォルダーが開かれていません。", vbExclamation
        Exit Sub
    End If

    If Not IsSearchFolder(fld) Then
        MsgBox "「" & fld.Name & "」は検索フォルダーではありません。" & vbCrLf & _
               "登録したい検索フォルダーを開いた状態で実行してください。", vbExclamation
        Exit Sub
    End If

    If modSearchFolderRegistry.IsRegistered(fld.StoreID, fld.EntryID) Then
        MsgBox "「" & fld.Name & "」はすでに登録済みです。", vbInformation
        Exit Sub
    End If

    Dim originalView As View
    Set originalView = expl.CurrentView
    Dim originalViewName As String
    originalViewName = originalView.Name
    Dim originalFilter As String
    originalFilter = originalView.Filter

    ' 専用ビューを複製する。元のビュー(originalView)はこの後も
    ' 一切変更しない。
    On Error Resume Next
    fld.Views.Item(modSearchFolderRegistry.DedicatedViewName).Delete
    On Error GoTo 0

    originalView.SaveAs modSearchFolderRegistry.DedicatedViewName, olViewSaveOptionThisFolderOnlyMe

    Dim dedicatedView As View
    Set dedicatedView = fld.Views.Item(modSearchFolderRegistry.DedicatedViewName)
    expl.CurrentView = dedicatedView

    modSearchFolderRegistry.RegisterFolder fld, originalViewName, originalFilter

    ApplyModeToFolder fld, modSearchFolderRegistry.GetGlobalMode(), expl

    MsgBox "「" & fld.Name & "」を管理対象に登録しました。", vbInformation
End Sub

Public Sub UnregisterCurrentFolder()
    Dim expl As Explorer
    Set expl = Application.ActiveExplorer
    If expl Is Nothing Then Exit Sub

    Dim fld As Folder
    Set fld = expl.CurrentFolder
    If fld Is Nothing Then Exit Sub

    If Not modSearchFolderRegistry.IsRegistered(fld.StoreID, fld.EntryID) Then
        MsgBox "「" & fld.Name & "」は登録されていません。", vbInformation
        Exit Sub
    End If

    RestoreFolderView fld, expl
    modSearchFolderRegistry.UnregisterFolder fld.StoreID, fld.EntryID

    On Error Resume Next
    fld.Views.Item(modSearchFolderRegistry.DedicatedViewName).Delete
    On Error GoTo 0

    MsgBox "「" & fld.Name & "」を管理対象から解除し、元の表示に戻しました。", vbInformation
End Sub

' ---- グローバルモード切替（操作マクロから直接呼ぶ） ----

Public Sub SetUnreadModeAll()
    modSearchFolderRegistry.SetGlobalMode "Unread"
    ApplyModeToAllOpenFolders "Unread"
End Sub

Public Sub SetAllModeAll()
    modSearchFolderRegistry.SetGlobalMode "All"
    ApplyModeToAllOpenFolders "All"
End Sub

' 現在開いているExplorerウィンドウのうち、管理対象フォルダーが
' 表示されているものだけに即時反映する。開いていないフォルダーは
' 次にそこへ移動した瞬間(OnFolderSwitch)に反映されるため、
' ここで登録フォルダー全件を走査する必要はない。
Private Sub ApplyModeToAllOpenFolders(mode As String)
    Dim expl As Explorer
    For Each expl In Application.Explorers
        Dim fld As Folder
        Set fld = CurrentExplorerFolder(expl)
        If Not fld Is Nothing Then
            If modSearchFolderRegistry.IsRegistered(fld.StoreID, fld.EntryID) Then
                ApplyModeToFolder fld, mode, expl
            End If
        End If
    Next expl
End Sub

' ---- フォルダー切替時の自動適用（ThisOutlookSession / clsExplorerWatcherから呼ぶ）----

Public Sub OnFolderSwitch(ByVal expl As Explorer)
    Dim fld As Folder
    Set fld = CurrentExplorerFolder(expl)
    If fld Is Nothing Then Exit Sub
    If Not modSearchFolderRegistry.IsRegistered(fld.StoreID, fld.EntryID) Then Exit Sub

    ApplyModeToFolder fld, modSearchFolderRegistry.GetGlobalMode(), expl
End Sub

' Outlook起動時、最初から開いている画面にも即座にモードを適用する。
' NewExplorerイベントは起動後に新規で開いたウィンドウにしか発火しないため、
' これが無いと最初の画面だけ前回のモードが反映されないまま残る。
Public Sub ApplyStartupMode()
    Dim expl As Explorer
    Set expl = Application.ActiveExplorer
    If expl Is Nothing Then Exit Sub
    OnFolderSwitch expl
End Sub

' ---- 実際のフィルター適用 ----

Private Sub ApplyModeToFolder(fld As Folder, mode As String, expl As Explorer)
    Dim vw As View
    On Error Resume Next
    Set vw = fld.Views.Item(modSearchFolderRegistry.DedicatedViewName)
    On Error GoTo 0
    If vw Is Nothing Then Exit Sub ' 専用ビュー未作成＝未登録として扱う

    If mode = "Unread" Then
        vw.Filter = modSearchFolderRegistry.UnreadFilterText
    Else
        vw.Filter = OriginalFilterFor(fld.StoreID, fld.EntryID)
    End If
    vw.Save

    If Not expl Is Nothing Then
        Dim shown As Folder
        Set shown = CurrentExplorerFolder(expl)
        If Not shown Is Nothing Then
            If shown.EntryID = fld.EntryID And shown.StoreID = fld.StoreID Then
                expl.CurrentView = vw ' 画面の再描画を確実にする
            End If
        End If
    End If
End Sub

Private Function OriginalFilterFor(storeID As String, entryID As String) As String
    Dim entries As Collection
    Set entries = modSearchFolderRegistry.AllRegisteredEntries()
    Dim e As Variant
    For Each e In entries
        If e(0) = storeID And e(1) = entryID Then
            OriginalFilterFor = e(4)
            Exit Function
        End If
    Next e
    OriginalFilterFor = ""
End Function

' ---- 復元 ----

Private Sub RestoreFolderView(fld As Folder, expl As Explorer)
    Dim entries As Collection
    Set entries = modSearchFolderRegistry.AllRegisteredEntries()
    Dim e As Variant
    For Each e In entries
        If e(0) = fld.StoreID And e(1) = fld.EntryID Then
            On Error Resume Next
            Dim originalView As View
            Set originalView = fld.Views.Item(e(3))
            If Not originalView Is Nothing Then
                expl.CurrentView = originalView
            End If
            On Error GoTo 0
            Exit Sub
        End If
    Next e
End Sub

Public Sub EmergencyRestoreAll()
    Dim entries As Collection
    Set entries = modSearchFolderRegistry.AllRegisteredEntries()

    Dim e As Variant
    For Each e In entries
        Dim fld As Folder
        Set fld = Nothing
        On Error Resume Next
        Set fld = Application.Session.GetFolderFromID(e(1), e(0))
        On Error GoTo 0

        If Not fld Is Nothing Then
            On Error Resume Next
            Dim originalView As View
            Set originalView = fld.Views.Item(e(3))
            If Not originalView Is Nothing Then
                originalView.Filter = e(4)
                originalView.Save
            End If
            fld.Views.Item(modSearchFolderRegistry.DedicatedViewName).Delete
            On Error GoTo 0
        End If
    Next e

    modSearchFolderRegistry.ClearAll
    MsgBox "すべての管理対象フォルダーを元の表示に戻し、制御を停止しました。", vbInformation
End Sub

' ---- 状態確認 ----

Public Sub ShowStatus()
    Dim entries As Collection
    Set entries = modSearchFolderRegistry.AllRegisteredEntries()

    If entries.Count = 0 Then
        MsgBox "現在、管理対象の検索フォルダーはありません。" & vbCrLf & _
               "現在のモード: " & modSearchFolderRegistry.GetGlobalMode, vbInformation
        Exit Sub
    End If

    Dim msg As String
    msg = "現在のモード: " & modSearchFolderRegistry.GetGlobalMode & vbCrLf & vbCrLf

    Dim e As Variant
    For Each e In entries
        Dim fld As Folder
        Set fld = Nothing
        On Error Resume Next
        Set fld = Application.Session.GetFolderFromID(e(1), e(0))
        On Error GoTo 0

        If fld Is Nothing Then
            msg = msg & "[無効] " & e(2) & "（フォルダーが見つかりません）" & vbCrLf
        Else
            msg = msg & "[有効] " & fld.Name & vbCrLf
        End If
    Next e

    MsgBox msg, vbInformation, "管理対象一覧"
End Sub

' ---- フェーズ0の実地確認をすぐ行うための診断マクロ ----
' 現在開いている検索フォルダーのビュー共有スコープとフィルターを表示する。
' 「この種類の全フォルダー共通」と出た場合でも、登録時に専用ビューへ
' 複製するため実害は無いが、事前確認用として残す。

Public Sub DiagnoseCurrentFolderView()
    Dim expl As Explorer
    Set expl = Application.ActiveExplorer
    If expl Is Nothing Then Exit Sub

    Dim fld As Folder
    Set fld = expl.CurrentFolder
    If fld Is Nothing Then Exit Sub

    Dim vw As View
    Set vw = expl.CurrentView

    Dim scopeText As String
    Select Case vw.SaveOption
        Case olViewSaveOptionThisFolderOnlyMe: scopeText = "このフォルダー・自分のみ"
        Case olViewSaveOptionThisFolderEveryone: scopeText = "このフォルダー・全員"
        Case olViewSaveOptionAllFoldersOfType: scopeText = "この種類の全フォルダー共通（★注意）"
        Case Else: scopeText = "不明(" & vw.SaveOption & ")"
    End Select

    MsgBox "フォルダー: " & fld.Name & vbCrLf & _
           "ビュー名: " & vw.Name & vbCrLf & _
           "共有範囲: " & scopeText & vbCrLf & _
           "現在のフィルター: [" & vw.Filter & "]", vbInformation, "ビュー診断"
End Sub
