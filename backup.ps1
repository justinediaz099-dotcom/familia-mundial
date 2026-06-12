# Run this anytime to manually snapshot index.html
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dest = "backups\index_$timestamp.html"
Copy-Item "index.html" $dest
Write-Output "Backup saved: $dest"
