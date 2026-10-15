VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "clsExplorerWatcher"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = False
Attribute VB_PredeclaredId = False
Attribute VB_Exposed = False
Option Explicit

' Outlookの画面(Explorer)1枚につき1個作られる見張り役。
' WithEventsで保持している間だけFolderSwitchイベントを受け取れるため、
' ThisOutlookSession側でこのインスタンスをCollectionに保持し続ける必要がある。

Public WithEvents WatchedExplorer As Outlook.Explorer

Private Sub WatchedExplorer_FolderSwitch()
    modSearchViewController.OnFolderSwitch WatchedExplorer
End Sub
