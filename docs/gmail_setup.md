# Gmail Setup for Email Drafts

## Initial Setup

1. **Create Google Cloud Project**
   - Go to: https://console.cloud.google.com/
   - Click "Select a project" → "New Project"
   - Name: `justin-job-apps` (or similar)
   - Click "Create"

2. **Enable Gmail API**
   - Go to: https://console.cloud.google.com/apis/library/gmail.googleapis.com
   - Click "Enable"

3. **Configure OAuth Consent Screen**
   - Go to: https://console.cloud.google.com/apis/credentials/consent
   - Select "External" → "Create"
   - Fill in:
     - App name: `Job Outreach`
     - User support email: your email
     - Developer contact: your email
   - Click "Save and Continue"
   - Scopes: Skip (added programmatically)
   - Test users: Add your Gmail address
   - Click "Save and Continue"

4. **Create OAuth Credentials**
   - Go to: https://console.cloud.google.com/apis/credentials
   - Click "Create Credentials" → "OAuth client ID"
   - Application type: "Desktop app"
   - Name: `job-outreach-cli`
   - Click "Create"
   - Click "Download JSON"

5. **Save Credentials**
   ```bash
   mkdir -p ~/.config/justin-jobs
   mv ~/Downloads/client_secret_*.json ~/.config/justin-jobs/client_secret.json
   ```

6. **Test Authentication**
   ```bash
   python3 -c "
   import sys
   from pathlib import Path
   sys.path.insert(0, str(Path('src')))
   from outreach.gmail_auth import test_connection
   print(f'Connected: {test_connection()}')
   "
   ```
   This will open a browser for OAuth consent on first run.

---

## Changing Gmail Account

To use a different Gmail account for drafts:

### Option 1: Delete existing token (quickest)

```bash
rm ~/.config/justin-jobs/token.json
```

Next time you run `/push email`, it will open a browser to authenticate with whichever Google account you choose.

### Option 2: Switch between multiple accounts

```bash
# Rename current token
mv ~/.config/justin-jobs/token.json ~/.config/justin-jobs/token-account1.json

# Next run will prompt for new account login
python3 src/outreach/push_email.py <job_id> --preview
```

To switch back:
```bash
mv ~/.config/justin-jobs/token-account1.json ~/.config/justin-jobs/token.json
```

### Option 3: Different Google Cloud project

If the new account is in a different Google Workspace or needs separate OAuth consent:

1. Create new OAuth credentials in Google Cloud Console
2. Download new `client_secret.json`
3. Replace `~/.config/justin-jobs/client_secret.json`
4. Delete `token.json` to force re-auth:
   ```bash
   rm ~/.config/justin-jobs/token.json
   ```

---

## Verify Current Account

```bash
python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('src')))
from outreach.gmail_auth import test_connection
print(f'Current account: {test_connection()}')
"
```

---

## File Locations

| File | Location | Purpose |
|------|----------|---------|
| OAuth credentials | `~/.config/justin-jobs/client_secret.json` | Google Cloud OAuth client |
| Access token | `~/.config/justin-jobs/token.json` | Cached authentication token |

Both files are stored outside the repo for security.

---

## Troubleshooting

**"OAuth credentials not found"**
- Download `client_secret.json` from Google Cloud Console
- Save to `~/.config/justin-jobs/client_secret.json`

**"Token has been revoked"**
- Delete token and re-authenticate:
  ```bash
  rm ~/.config/justin-jobs/token.json
  ```

**Wrong account**
- Delete token to force account selection:
  ```bash
  rm ~/.config/justin-jobs/token.json
  ```
