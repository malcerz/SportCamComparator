$Cert = Get-ChildItem Cert:\CurrentUser\My | Where-Object { $_.Subject -eq "CN=E2A524DB-9E81-4D08-A86B-40EA6B42DED4" } | Select-Object -First 1
if (-not $Cert) {
    Write-Host "Certyfikat DEV nie zostal znaleziony w CurrentUser\My."
    exit 1
}
Export-Certificate -Cert $Cert -FilePath "MalcerzDev_Official.cer" -Force
Write-Host "Aby zainstalowac MSIX z prawidlowym podpisem DEV, musisz dodac powyzszy certyfikat do Zaufanych Osob (TrustedPeople) w LocalMachine."
Write-Host "========================================================="
Write-Host "Uruchom ponizsza komende w PowerShellu JAKO ADMINISTRATOR:"
Write-Host "Import-Certificate -FilePath `"$PWD\MalcerzDev_Official.cer`" -CertStoreLocation Cert:\LocalMachine\TrustedPeople"
Write-Host "========================================================="
