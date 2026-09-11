Attribute VB_Name = "modSearchFolderRegistry"
Option Explicit

' 登録済み検索フォルダーの台帳を Windows のユーザー設定領域
' (HKCU\Software\VB and VBA Program Settings) へ保存・照合するモジュール。
' フォルダー本体には一切触れず、文字列の読み書きだけを行う。

Private Const APP_NAME As String = "OutlookSearchFolderViewToggle"
Private Const SECTION_REGISTRY As String = "Registry"
Private Const SECTION_GLOBAL As String = "Global"
Private Const DEDICATED_VIEW_NAME As String = "SFVT_Managed"

' FolderSwitch は連続発火しうるため、登録済みかどうかをO(1)で
' 判定できるようメモリ上にも索引を持つ。
Private mIndex As Object ' Scripting.Dictionary

Public Function DedicatedViewName() As String
    DedicatedViewName = DEDICATED_VIEW_NAME
End Function

' 簡易記法([Unread] = 0/1)がこの環境の解析エンジンで
' 受け付けられなかったため、Outlookが内部で使う正式なプロパティ名を
' 直接指定するDASL記法に変更した。
Public Function UnreadFilterText() As String
    UnreadFilterText = "@SQL=" & Chr(34) & "urn:schemas:httpmail:read" & Chr(34) & " = 0"
End Function

' StoreID・EntryIDは長い16進文字列で、そのままレジストリの「値の名前」に
' 使うと長さ上限に触れる恐れがある。そのため保存キー名は短い連番("F1","F2"...)
' にし、StoreID・EntryIDは値の中身（IdentityKey）としてのみ扱う。
Private Function IdentityKey(storeID As String, entryID As String) As String
    IdentityKey = storeID & "|" & entryID
End Function

Private Function FindStorageKey(storeID As String, entryID As String) As String
    Dim data As Variant
    data = GetAllSettings(APP_NAME, SECTION_REGISTRY)
    If IsEmpty(data) Then Exit Function

    Dim i As Long
    For i = LBound(data, 1) To UBound(data, 1)
        Dim parts() As String
        parts = Split(data(i, 1), "|")
        If parts(0) = storeID And parts(1) = entryID Then
            FindStorageKey = data(i, 0)
            Exit Function
        End If
    Next i
End Function

Private Function NextStorageKey() As String
    Dim n As Long
    n = CLng(GetSetting(APP_NAME, SECTION_GLOBAL, "NextSequence", "1"))
    SaveSetting APP_NAME, SECTION_GLOBAL, "NextSequence", CStr(n + 1)
    NextStorageKey = "F" & n
End Function

Private Sub EnsureIndexLoaded()
    If Not mIndex Is Nothing Then Exit Sub
    Set mIndex = CreateObject("Scripting.Dictionary")

    Dim data As Variant
    data = GetAllSettings(APP_NAME, SECTION_REGISTRY)
    If IsEmpty(data) Then Exit Sub

    Dim i As Long
    For i = LBound(data, 1) To UBound(data, 1)
        Dim parts() As String
        parts = Split(data(i, 1), "|")
        mIndex(IdentityKey(parts(0), parts(1))) = True
    Next i
End Sub

Public Function IsRegistered(storeID As String, entryID As String) As Boolean
    EnsureIndexLoaded
    IsRegistered = mIndex.Exists(IdentityKey(storeID, entryID))
End Function

' レコード形式(値の中身): StoreID|EntryID|FolderName|OriginalViewName|OriginalFilter
Public Sub RegisterFolder(fld As Folder, originalViewName As String, originalFilter As String)
    Dim value As String
    value = fld.StoreID & "|" & fld.EntryID & "|" & fld.Name & "|" & originalViewName & "|" & originalFilter

    Dim storageKey As String
    storageKey = FindStorageKey(fld.StoreID, fld.EntryID)
    If storageKey = "" Then storageKey = NextStorageKey()

    SaveSetting APP_NAME, SECTION_REGISTRY, storageKey, value

    EnsureIndexLoaded
    mIndex(IdentityKey(fld.StoreID, fld.EntryID)) = True
End Sub

Public Sub UnregisterFolder(storeID As String, entryID As String)
    Dim storageKey As String
    storageKey = FindStorageKey(storeID, entryID)
    If storageKey <> "" Then
        On Error Resume Next
        DeleteSetting APP_NAME, SECTION_REGISTRY, storageKey
        On Error GoTo 0
    End If

    EnsureIndexLoaded
    If mIndex.Exists(IdentityKey(storeID, entryID)) Then mIndex.Remove IdentityKey(storeID, entryID)
End Sub

' 全登録レコードを Collection で返す。各要素は
' Array(StoreID, EntryID, FolderName, OriginalViewName, OriginalFilter)
Public Function AllRegisteredEntries() As Collection
    Dim result As New Collection
    Dim data As Variant
    data = GetAllSettings(APP_NAME, SECTION_REGISTRY)
    If IsEmpty(data) Then
        Set AllRegisteredEntries = result
        Exit Function
    End If

    Dim i As Long
    For i = LBound(data, 1) To UBound(data, 1)
        result.Add Split(data(i, 1), "|")
    Next i
    Set AllRegisteredEntries = result
End Function

Public Function GetGlobalMode() As String
    GetGlobalMode = GetSetting(APP_NAME, SECTION_GLOBAL, "Mode", "All")
End Function

Public Sub SetGlobalMode(mode As String)
    SaveSetting APP_NAME, SECTION_GLOBAL, "Mode", mode
End Sub

Public Sub ClearAll()
    On Error Resume Next
    DeleteSetting APP_NAME, SECTION_REGISTRY
    On Error GoTo 0
    Set mIndex = Nothing
End Sub
