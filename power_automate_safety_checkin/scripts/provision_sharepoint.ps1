<#
.SYNOPSIS
    地震安否確認システム用のSharePointリスト(5個)と列を自動作成し、
    拠点定義(config/sites.json)とメンバー一覧(config/members.example.json)を
    一括投入する。

.DESCRIPTION
    docs/03_SHAREPOINT_SCHEMA.md のスキーマに準拠する。
    このスクリプトはPnP.PowerShellモジュールを使用する。
    GUIでリスト・列を1つずつ作成する作業、およびメンバーを1行ずつ
    手入力する作業を、すべてこのスクリプトで代替することを目的とする。

    実行前に一度だけ、対話的なサインイン(Connect-PnPOnline -Interactive)が必要になる。
    これはSharePoint Onlineへの認証であり、自動化できない唯一の手作業である。

.PARAMETER SiteUrl
    対象のSharePointサイトURL（例: https://yourtenant.sharepoint.com/sites/EQSafetyCheckin）

.PARAMETER MembersFile
    投入するメンバー一覧JSONのパス。既定は config/members.example.json のプレースホルダ。
    本番投入前に、実際のメンバー情報を記載した config/members.json を用意し、
    このパラメータで指定すること（members.json はコミットしないこと）。

.EXAMPLE
    Install-Module PnP.PowerShell -Scope CurrentUser
    ./provision_sharepoint.ps1 -SiteUrl "https://contoso.sharepoint.com/sites/EQSafetyCheckin" `
        -MembersFile "../config/members.json"
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$SiteUrl,

    [string]$SitesFile = (Join-Path $PSScriptRoot "../config/sites.json"),
    [string]$MembersFile = (Join-Path $PSScriptRoot "../config/members.example.json")
)

$ErrorActionPreference = "Stop"

function Get-OrCreateList {
    param(
        [Parameter(Mandatory = $true)][string]$Title
    )
    $list = Get-PnPList -Identity $Title -ErrorAction SilentlyContinue
    if ($null -eq $list) {
        Write-Host "[CREATE] List: $Title"
        $list = New-PnPList -Title $Title -Template GenericList -EnableVersioning
    }
    else {
        Write-Host "[SKIP] List already exists: $Title"
    }
    return $list
}

function Add-FieldIfMissing {
    param(
        [Parameter(Mandatory = $true)]$List,
        [Parameter(Mandatory = $true)][string]$InternalName,
        [Parameter(Mandatory = $true)][string]$DisplayName,
        [Parameter(Mandatory = $true)][string]$Type,
        [string[]]$Choices,
        [switch]$Required
    )
    $existing = Get-PnPField -List $List -Identity $InternalName -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        Write-Host "  [SKIP] Field exists: $InternalName"
        return
    }
    Write-Host "  [CREATE] Field: $InternalName ($Type)"
    $params = @{
        List        = $List
        DisplayName = $DisplayName
        InternalName = $InternalName
        Type        = $Type
        AddToDefaultView = $true
    }
    if ($Choices) { $params["Choices"] = $Choices }
    if ($Required) { $params["Required"] = $true }
    Add-PnPField @params | Out-Null
}

function Set-TitleFieldLabel {
    param(
        [Parameter(Mandatory = $true)]$List,
        [Parameter(Mandatory = $true)][string]$Label
    )
    Set-PnPField -List $List -Identity "Title" -Values @{ Title = $Label } | Out-Null
}

function Set-UniqueField {
    param(
        [Parameter(Mandatory = $true)]$List,
        [Parameter(Mandatory = $true)][string]$InternalName
    )
    Set-PnPField -List $List -Identity $InternalName -Values @{ EnforceUniqueValues = $true; Indexed = $true } | Out-Null
}

Write-Host "=== Connecting to $SiteUrl ==="
Connect-PnPOnline -Url $SiteUrl -Interactive

# ---------------------------------------------------------------------------
# EQ_Config_Sites
# ---------------------------------------------------------------------------
Write-Host "`n=== EQ_Config_Sites ==="
$sitesList = Get-OrCreateList -Title "EQ_Config_Sites"
Set-TitleFieldLabel -List $sitesList -Label "SiteCode"
Add-FieldIfMissing -List $sitesList -InternalName "SiteName" -DisplayName "SiteName" -Type Text -Required
Add-FieldIfMissing -List $sitesList -InternalName "PrefectureTokens" -DisplayName "PrefectureTokens" -Type Note
Add-FieldIfMissing -List $sitesList -InternalName "MunicipalityTokens" -DisplayName "MunicipalityTokens" -Type Note
Add-FieldIfMissing -List $sitesList -InternalName "AlertThresholdCode" -DisplayName "AlertThresholdCode" -Type Choice -Choices @("1","2","3","4","5-","5+","6-","6+","7")
Add-FieldIfMissing -List $sitesList -InternalName "AlertThresholdValue" -DisplayName "AlertThresholdValue" -Type Number
Add-FieldIfMissing -List $sitesList -InternalName "TeamId" -DisplayName "TeamId" -Type Text
Add-FieldIfMissing -List $sitesList -InternalName "ChannelId" -DisplayName "ChannelId" -Type Text
Add-FieldIfMissing -List $sitesList -InternalName "IsActive" -DisplayName "IsActive" -Type Boolean
Add-FieldIfMissing -List $sitesList -InternalName "TestMode" -DisplayName "TestMode" -Type Boolean
Set-UniqueField -List $sitesList -InternalName "Title"

# ---------------------------------------------------------------------------
# EQ_Config_Members
# ---------------------------------------------------------------------------
Write-Host "`n=== EQ_Config_Members ==="
$membersList = Get-OrCreateList -Title "EQ_Config_Members"
Set-TitleFieldLabel -List $membersList -Label "EmployeeID"
Add-FieldIfMissing -List $membersList -InternalName "DisplayName" -DisplayName "DisplayName" -Type Text -Required
Add-FieldIfMissing -List $membersList -InternalName "Email" -DisplayName "Email" -Type Text -Required
Add-FieldIfMissing -List $membersList -InternalName "SiteCode" -DisplayName "SiteCode" -Type Text -Required
Add-FieldIfMissing -List $membersList -InternalName "IsActive" -DisplayName "IsActive" -Type Boolean
Add-FieldIfMissing -List $membersList -InternalName "IsManager" -DisplayName "IsManager" -Type Boolean
Add-FieldIfMissing -List $membersList -InternalName "EscalationOrder" -DisplayName "EscalationOrder" -Type Number
Set-UniqueField -List $membersList -InternalName "Title"

# ---------------------------------------------------------------------------
# EQ_Received_Items
# ---------------------------------------------------------------------------
Write-Host "`n=== EQ_Received_Items ==="
$receivedList = Get-OrCreateList -Title "EQ_Received_Items"
Set-TitleFieldLabel -List $receivedList -Label "SourceEntryId"
Add-FieldIfMissing -List $receivedList -InternalName "SourceUpdatedAt" -DisplayName "SourceUpdatedAt" -Type DateTime
Add-FieldIfMissing -List $receivedList -InternalName "SourceLink" -DisplayName "SourceLink" -Type URL
Add-FieldIfMissing -List $receivedList -InternalName "InformationType" -DisplayName "InformationType" -Type Text
Add-FieldIfMissing -List $receivedList -InternalName "ProcessingStatus" -DisplayName "ProcessingStatus" -Type Choice -Choices @("New","Processed","Ignored","Error")
Add-FieldIfMissing -List $receivedList -InternalName "ErrorCode" -DisplayName "ErrorCode" -Type Text
Add-FieldIfMissing -List $receivedList -InternalName "ErrorDetail" -DisplayName "ErrorDetail" -Type Note
Set-UniqueField -List $receivedList -InternalName "Title"

# ---------------------------------------------------------------------------
# EQ_Events
# ---------------------------------------------------------------------------
Write-Host "`n=== EQ_Events ==="
$eventsList = Get-OrCreateList -Title "EQ_Events"
Set-TitleFieldLabel -List $eventsList -Label "EventID"
Add-FieldIfMissing -List $eventsList -InternalName "SourceEntryId" -DisplayName "SourceEntryId" -Type Text
Add-FieldIfMissing -List $eventsList -InternalName "SiteCode" -DisplayName "SiteCode" -Type Text -Required
Add-FieldIfMissing -List $eventsList -InternalName "OccurredAt" -DisplayName "OccurredAt" -Type DateTime
Add-FieldIfMissing -List $eventsList -InternalName "PublishedAt" -DisplayName "PublishedAt" -Type DateTime
Add-FieldIfMissing -List $eventsList -InternalName "Epicenter" -DisplayName "Epicenter" -Type Text
Add-FieldIfMissing -List $eventsList -InternalName "Magnitude" -DisplayName "Magnitude" -Type Number
Add-FieldIfMissing -List $eventsList -InternalName "SiteIntensityCode" -DisplayName "SiteIntensityCode" -Type Text
Add-FieldIfMissing -List $eventsList -InternalName "SiteIntensityValue" -DisplayName "SiteIntensityValue" -Type Number
Add-FieldIfMissing -List $eventsList -InternalName "AlertStatus" -DisplayName "AlertStatus" -Type Choice -Choices @("Open","Closed","Cancelled")
Add-FieldIfMissing -List $eventsList -InternalName "StartedBy" -DisplayName "StartedBy" -Type Choice -Choices @("Auto","Manual")
Add-FieldIfMissing -List $eventsList -InternalName "IsTest" -DisplayName "IsTest" -Type Boolean
Set-UniqueField -List $eventsList -InternalName "Title"

# ---------------------------------------------------------------------------
# EQ_Responses
# ---------------------------------------------------------------------------
Write-Host "`n=== EQ_Responses ==="
$responsesList = Get-OrCreateList -Title "EQ_Responses"
Set-TitleFieldLabel -List $responsesList -Label "ResponseKey"
Add-FieldIfMissing -List $responsesList -InternalName "EventID" -DisplayName "EventID" -Type Text -Required
Add-FieldIfMissing -List $responsesList -InternalName "EmployeeID" -DisplayName "EmployeeID" -Type Text -Required
Add-FieldIfMissing -List $responsesList -InternalName "Email" -DisplayName "Email" -Type Text
Add-FieldIfMissing -List $responsesList -InternalName "ResponseCode" -DisplayName "ResponseCode" -Type Choice -Choices @("1","2","3","4")
Add-FieldIfMissing -List $responsesList -InternalName "SafetyStatus" -DisplayName "SafetyStatus" -Type Choice -Choices @("Safe","Affected")
Add-FieldIfMissing -List $responsesList -InternalName "WorkStatus" -DisplayName "WorkStatus" -Type Choice -Choices @("Available","Unavailable")
Add-FieldIfMissing -List $responsesList -InternalName "RespondedAt" -DisplayName "RespondedAt" -Type DateTime
Add-FieldIfMissing -List $responsesList -InternalName "Comment" -DisplayName "Comment" -Type Note
Add-FieldIfMissing -List $responsesList -InternalName "Escalated" -DisplayName "Escalated" -Type Boolean
Add-FieldIfMissing -List $responsesList -InternalName "Revision" -DisplayName "Revision" -Type Number
Set-UniqueField -List $responsesList -InternalName "Title"

# ---------------------------------------------------------------------------
# データ投入: 拠点(sites.json)
# ---------------------------------------------------------------------------
Write-Host "`n=== Loading sites from $SitesFile ==="
$sites = Get-Content -Raw -Path $SitesFile | ConvertFrom-Json
foreach ($site in $sites) {
    $existingItem = Get-PnPListItem -List $sitesList -Query "<View><Query><Where><Eq><FieldRef Name='Title'/><Value Type='Text'>$($site.siteCode)</Value></Eq></Where></Query></View>"
    if ($existingItem) {
        Write-Host "  [SKIP] Site already exists: $($site.siteCode)"
        continue
    }
    Write-Host "  [ADD] Site: $($site.siteCode)"
    Add-PnPListItem -List $sitesList -Values @{
        Title               = $site.siteCode
        SiteName            = $site.siteName
        PrefectureTokens    = ($site.prefectureTokens -join ";")
        MunicipalityTokens  = ($site.municipalityTokens -join ";")
        AlertThresholdCode  = $site.thresholdCode
        AlertThresholdValue = $site.thresholdValue
        TeamId              = $site.teamId
        ChannelId           = $site.channelId
        IsActive            = $site.isActive
        TestMode            = $site.testMode
    } | Out-Null
}

# ---------------------------------------------------------------------------
# データ投入: メンバー(members.json / members.example.json)
# ---------------------------------------------------------------------------
Write-Host "`n=== Loading members from $MembersFile ==="
$members = Get-Content -Raw -Path $MembersFile | ConvertFrom-Json
foreach ($member in $members) {
    $existingItem = Get-PnPListItem -List $membersList -Query "<View><Query><Where><Eq><FieldRef Name='Title'/><Value Type='Text'>$($member.employeeId)</Value></Eq></Where></Query></View>"
    if ($existingItem) {
        Write-Host "  [SKIP] Member already exists: $($member.employeeId)"
        continue
    }
    Write-Host "  [ADD] Member: $($member.employeeId) ($($member.displayName))"
    Add-PnPListItem -List $membersList -Values @{
        Title           = $member.employeeId
        DisplayName     = $member.displayName
        Email           = $member.email
        SiteCode        = $member.siteCode
        IsActive        = $member.isActive
        IsManager       = $member.isManager
        EscalationOrder = $member.escalationOrder
    } | Out-Null
}

Write-Host "`n=== Done. 5 lists ready, sites and members loaded. ==="
Write-Host "Next: create SharePoint columns' internal names snapshot for Gate D evidence:"
Write-Host "  Get-PnPField -List EQ_Config_Sites | Select DisplayName, InternalName | Format-Table"
