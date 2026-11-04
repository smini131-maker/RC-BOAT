param([switch]$Install)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $env:ANDROID_HOME) { $env:ANDROID_HOME = Join-Path $env:USERPROFILE 'AndroidSdk' }
if (-not (Test-Path -LiteralPath $env:ANDROID_HOME)) { throw 'Android SDK가 없습니다. Android Studio SDK 설치 후 ANDROID_HOME을 지정하세요.' }
$signDir=Join-Path $env:USERPROFILE '.rcboat'
New-Item -ItemType Directory -Path $signDir -Force | Out-Null
$signFile=Join-Path $signDir 'android-signing.properties'
if (-not (Test-Path -LiteralPath $signFile)) {
    $randomBytes=New-Object byte[] 24
    $rng=[System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($randomBytes) } finally { $rng.Dispose() }
    $env:RCBOAT_SIGN_PASS=[BitConverter]::ToString($randomBytes).Replace('-','')
    $key=Join-Path $signDir 'rcboat-mobile.jks'
    & keytool -genkeypair -keystore $key -alias rcboat -keyalg RSA -keysize 3072 -validity 10000 -dname 'CN=RCBoat Mobile' -storepass:env RCBOAT_SIGN_PASS -keypass:env RCBOAT_SIGN_PASS -noprompt
    if ($LASTEXITCODE -ne 0) { throw '서명 키 생성 실패' }
    @("storeFile=$($key.Replace('\','/').Replace(':','\:'))", "storePassword=$env:RCBOAT_SIGN_PASS", 'keyAlias=rcboat', "keyPassword=$env:RCBOAT_SIGN_PASS") | Set-Content -LiteralPath $signFile -Encoding ascii
    Remove-Item Env:RCBOAT_SIGN_PASS
}
$version=(Get-Content -LiteralPath '..\VERSION' -Raw).Trim()
# AAPT/Gradle on Windows do not reliably support the Korean OneDrive path.
$stage=Join-Path $env:LOCALAPPDATA ('RCBoatBuild\android\source-'+[Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage -Force | Out-Null
& robocopy $PSScriptRoot $stage /E /XD build .gradle /XF local.properties /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw 'Android 빌드 소스 준비 실패' }
('sdk.dir=' + $env:ANDROID_HOME.Replace('\','/').Replace(':','\:')) | Set-Content -LiteralPath (Join-Path $stage 'local.properties') -Encoding ascii
Push-Location -LiteralPath $stage
try { & .\gradlew.bat --no-daemon testDebugUnitTest lintDebug assembleRelease } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { throw 'Android 빌드/검증 실패' }
$output=Join-Path (Split-Path -Parent $PSScriptRoot) 'dist'
New-Item -ItemType Directory -Path $output -Force | Out-Null
$apk=Join-Path $output "RCBoatMobile_v$version.apk"
Copy-Item -LiteralPath (Join-Path $stage 'app\build\outputs\apk\release\app-release.apk') -Destination $apk -Force
$reports=Join-Path $output 'android-validation'
New-Item -ItemType Directory -Path $reports -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $stage 'app\build\reports') -Destination $reports -Recurse -Force
Get-FileHash -LiteralPath $apk -Algorithm SHA256
if ($Install) {
    & (Join-Path $env:ANDROID_HOME 'platform-tools\adb.exe') install -r $apk
    if ($LASTEXITCODE -ne 0) { throw 'APK 설치 실패 · USB 디버깅 연결을 확인하세요' }
}
