# Auto-runs before every git push — saves backup + validates player count
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dest = "backups\index_$timestamp.html"
Copy-Item "index.html" $dest
Write-Output "Backup saved: $dest"

# Run validation
python verify.py
type check_output.txt
