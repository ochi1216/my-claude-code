<#
.SYNOPSIS
    Power Platform CLI (pac) を使い、DEVで一度だけ構築したSolutionを
    TEST/PRODへ再構築なしで展開する。

.DESCRIPTION
    Power AutomateのCloud Flowは、GUIでの初回構築なしに完全にゼロから
    JSONだけで生成することはできない（Microsoft側の設計上の制約）。
    そのため、このスクリプトが前提とする手順は次の通り:

      1. DEV環境で、docs/FLOW_LOGIC_SPEC.md の通りに5フローを1回だけGUIで構築し、
         1つのSolution（例: EQSafetyCheckin）にまとめる。
      2. 以降のTEST/PRODへの展開、および将来の修正反映は、
         このスクリプトによるexport/unpack/pack/importで行う。GUIでの再構築は不要。

    このスクリプトは以下を自動化する。
      - DEV環境からのSolutionエクスポート
      - source管理用フォルダへのunpack（Gitで差分管理できる形式）
      - 別環境（TEST/PROD）へのpack & import

    唯一の手作業は、各環境への初回サインイン（pac auth create、対話的）と、
    接続参照（Connection Reference）の初回承認である。これはMicrosoftの
    セキュリティモデル上、スクリプトからは代替できない。

.PARAMETER Action
    export-unpack | pack-import

.PARAMETER SolutionName
    Solutionの一意名（表示名ではなく Unique Name）。例: EQSafetyCheckin

.PARAMETER SourcePath
    unpack先/pack元のソースフォルダ（Gitでバージョン管理する）。
    既定: power_automate_safety_checkin/solution/<SolutionName>

.PARAMETER EnvironmentUrl
    対象環境のURL（例: https://contoso.crm7.dynamics.com もしくは
    Power Automate環境のURL）。export-unpack時はDEV、pack-import時はTEST/PROD。

.PARAMETER Managed
    pack-import時に管理ソリューション(Managed)としてimportする場合に指定。
    TEST/PRODへはManaged、DEVでの継続編集にはUnmanagedを推奨。

.EXAMPLE
    # DEVで構築したSolutionをエクスポート・unpackしてGit管理下に置く
    ./deploy_solution.ps1 -Action export-unpack `
        -SolutionName "EQSafetyCheckin" `
        -EnvironmentUrl "https://contoso-dev.crm7.dynamics.com"

.EXAMPLE
    # source管理下のSolutionをpackしてTEST環境へimport
    ./deploy_solution.ps1 -Action pack-import `
        -SolutionName "EQSafetyCheckin" `
        -EnvironmentUrl "https://contoso-test.crm7.dynamics.com" `
        -Managed
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("export-unpack", "pack-import")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$SolutionName,

    [Parameter(Mandatory = $true)]
    [string]$EnvironmentUrl,

    [string]$SourcePath = (Join-Path $PSScriptRoot "../solution/$SolutionName"),
    [string]$WorkDir = (Join-Path $PSScriptRoot "../.pac-work"),

    [switch]$Managed
)

$ErrorActionPreference = "Stop"

function Assert-PacCliInstalled {
    $pac = Get-Command pac -ErrorAction SilentlyContinue
    if ($null -eq $pac) {
        Write-Error @"
pac CLI が見つかりません。以下のいずれかでインストールしてください。
  dotnet tool install --global Microsoft.PowerApps.CLI.Tool
  (または) https://aka.ms/PowerAppsCLI からインストーラーを取得

インストール後、一度だけ以下でサインインしてください（対話的、代替不可）。
  pac auth create --url $EnvironmentUrl
"@
    }
}

Assert-PacCliInstalled
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

Write-Host "=== Selecting auth profile for $EnvironmentUrl ==="
pac auth select --environment $EnvironmentUrl 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "認証プロファイルが見つかりません。初回サインインを行います(対話的)。"
    pac auth create --url $EnvironmentUrl
}

if ($Action -eq "export-unpack") {
    $zipPath = Join-Path $WorkDir "$SolutionName.zip"

    Write-Host "=== Exporting solution '$SolutionName' from $EnvironmentUrl ==="
    pac solution export --name $SolutionName --path $zipPath --managed false
    if ($LASTEXITCODE -ne 0) { throw "pac solution export failed" }

    Write-Host "=== Unpacking to $SourcePath (source-controlled) ==="
    New-Item -ItemType Directory -Force -Path $SourcePath | Out-Null
    pac solution unpack --zipfile $zipPath --folder $SourcePath --packagetype Unmanaged --allowWrite true
    if ($LASTEXITCODE -ne 0) { throw "pac solution unpack failed" }

    Write-Host "`n=== Done. Commit $SourcePath to Git for version control and review. ==="
}
elseif ($Action -eq "pack-import") {
    if (-not (Test-Path $SourcePath)) {
        throw "Source path not found: $SourcePath. まず export-unpack をDEVに対して実行してください。"
    }

    $zipPath = Join-Path $WorkDir "$SolutionName-pack.zip"
    $packageType = if ($Managed) { "Managed" } else { "Unmanaged" }

    Write-Host "=== Packing solution from $SourcePath (as $packageType) ==="
    pac solution pack --zipfile $zipPath --folder $SourcePath --packagetype $packageType
    if ($LASTEXITCODE -ne 0) { throw "pac solution pack failed" }

    Write-Host "=== Importing into $EnvironmentUrl ==="
    pac solution import --path $zipPath --async true --force-overwrite
    if ($LASTEXITCODE -ne 0) { throw "pac solution import failed" }

    Write-Host "`n=== Done. Verify flows are turned on and connection references are mapped in $EnvironmentUrl. ==="
    Write-Host "接続参照(Connection Reference)の紐付けは、環境ごとに初回のみGUIでの承認が必要です。"
}
