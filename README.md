# simple-uploader

**Copy something. Press a shortcut. Get a link.**

Upload your clipboard to your own S3-compatible storage. Images, videos, text,
Markdown, PDFs, archives, or files copied from your file manager: review what
you're sharing in a small confirmation dialog, click **Upload**, and paste the URL.

```text
Copy → Ctrl+Shift+Alt+U → Confirm → Upload → Paste the link
```

Built for Linux, with Wayland and X11 support. Tested on **Pop!_OS 24.04 with
COSMIC / Wayland**. Follows
[simple-screen-capture](https://github.com/KerryRitter/simple-screen-capture)'s
small scripts, `s3.conf` settings, and standard-library SigV4 uploader pattern.

## Features

- **One shortcut:** `Ctrl+Shift+Alt+U` opens the upload dialog.
- **Preview before sharing:** image thumbnails, text previews, and file details.
- **Your storage:** Cloudflare R2, AWS S3, Backblaze B2, MinIO, or another
  S3-compatible service.
- **Text or Markdown:** choose the format in the dialog and edit the filename.
- **Multiple files:** upload a selection and get one URL per line.
- **Small footprint:** no background daemon, AWS CLI, or pip packages required.

## Install

### Pop!_OS, Ubuntu, and Debian

Run these commands in a terminal in your desktop session:

```bash
# Install desktop dependencies.
sudo apt install git python3-gi gir1.2-gtk-3.0 wl-clipboard xclip

# Download and install simple-uploader.
git clone https://github.com/KerryRitter/simple-uploader.git
cd simple-uploader
./install.sh

# Enter your S3/R2 settings in the setup dialog.
~/.local/bin/simple-uploader --setup
```

Copy some text or an image, then press **Ctrl+Shift+Alt+U**. Confirm the upload
and paste the resulting URL wherever you want to share it.

The installer puts the app under `~/.local`, adds an app launcher, and registers the shortcut on
COSMIC or GNOME. Existing shortcuts are preserved; a conflicting binding is
reported. Run `./install.sh` as your normal user; only the dependency installation
above requires `sudo`.

If GTK is already installed, you can start with the `git clone` step. On
Pop!_OS/Ubuntu, the installer can download and install missing Wayland clipboard
tools into `~/.local/bin` without root.

### Other Linux desktops

Requires **Python 3.10+**, GTK 3 / PyGObject, and `wl-clipboard` on Wayland or
`xclip` on X11. Install those packages with your distribution's package manager,
then run:

```bash
git clone https://github.com/KerryRitter/simple-uploader.git
cd simple-uploader
./install.sh --no-shortcut
~/.local/bin/simple-uploader --setup
```

Add a custom shortcut in your desktop's keyboard settings:

| Setting | Value |
| --- | --- |
| Name | Simple Uploader |
| Shortcut | `Ctrl+Shift+Alt+U` |
| Command | The full path to `~/.local/bin/simple-uploader`, such as `/home/you/.local/bin/simple-uploader` |

Automatic shortcut registration supports COSMIC and GNOME. Clipboard support on
other Wayland desktops depends on the compositor's support for `wl-clipboard`.
macOS and Windows are not currently supported.

## Configure S3 / R2

Open the settings dialog at any time:

```bash
~/.local/bin/simple-uploader --setup
```

You can also copy something and press the shortcut: if configuration is missing,
the app opens setup before asking you to confirm the upload.

### Cloudflare R2

1. Create an R2 bucket.
2. Create an [R2 API token](https://developers.cloudflare.com/r2/api/tokens/) with
   **Object Read and Write** access to that bucket. Save its **Access Key ID** and
   **Secret Access Key**.
3. Set up [public access](https://developers.cloudflare.com/r2/buckets/public-buckets/)
   through a custom domain. An enabled `r2.dev` URL also works for development.
4. Enter these settings in simple-uploader:

| Field | Example |
| --- | --- |
| Endpoint URL | `https://YOUR-ACCOUNT-ID.r2.cloudflarestorage.com` |
| Bucket name | `my-uploads` |
| Region | `auto` |
| Access key ID | Your R2 Access Key ID |
| Secret access key | Your R2 Secret Access Key |
| Path prefix | `uploads/` |
| Public URL base | `https://files.example.com` |
| ACL | Leave blank |

The **endpoint** is the API address used to upload. The **public URL base** is
the address people use to view your files. They are usually different addresses.

### Other S3-compatible storage

- **AWS S3:** Use the bucket's regional endpoint and region. For anonymous reads,
  configure a public bucket policy or use `S3_ACL=public-read` if your bucket permits ACLs.
- **B2 / MinIO:** Supply your S3-compatible endpoint, bucket, region, and public URL.
- **Temporary AWS credentials:** Set `S3_SESSION_TOKEN` too.

`S3_PUBLIC_URL_BASE` should point to the public bucket root, without the path
prefix. The prefix and unique filename are appended automatically. For example:

```text
https://files.example.com/uploads/20261025-153000-a1b2c3d4e5f6-clipboard.png
```

**Shareable links require public read access.** Upload credentials alone do not
make an object public. Without a public base, the upload URL is returned, which
may require authentication to open. The app does not change bucket policies or
generate expiring, presigned links.

### Configuration file

Config is saved as `~/.config/simple-uploader/s3.conf` with mode `600`. If that
file does not exist, an existing `~/.config/capture/s3.conf` is used automatically.
`--setup` edits whichever config is selected, including the shared capture config.
Use `--config /path/to/s3.conf` to choose another file. `XDG_CONFIG_HOME` is honored.

To create a separate config even when a shared capture config exists:

```bash
~/.local/bin/simple-uploader --config ~/.config/simple-uploader/s3.conf --setup
```

| Key | Required | Purpose |
| --- | --- | --- |
| `S3_ENDPOINT` | Yes | S3 API endpoint, without the bucket name |
| `S3_BUCKET` | Yes | Bucket name |
| `S3_ACCESS_KEY_ID` | Yes | Upload access key ID |
| `S3_SECRET_ACCESS_KEY` | Yes | Upload secret access key |
| `S3_REGION` | No | Signing region; defaults to `auto` |
| `S3_PATH_PREFIX` | No | Object key prefix; setup suggests `uploads/` |
| `S3_PUBLIC_URL_BASE` | No | Public bucket root or CDN URL |
| `S3_ACL` | No | Object ACL; leave blank for R2 |
| `S3_SESSION_TOKEN` | No | Session token for temporary credentials |

Prefer editing a file? From the checkout:

```bash
mkdir -p ~/.config/simple-uploader
install -m 600 s3.conf.example ~/.config/simple-uploader/s3.conf
${EDITOR:-nano} ~/.config/simple-uploader/s3.conf
```

Fill in the placeholders from [s3.conf.example](s3.conf.example). Shell-style
quotes are accepted; config is parsed as data, never executed.

## Clipboard behavior

- **Images:** Upload the clipboard image bytes; a thumbnail appears for supported
  image formats. PNG is preferred when multiple image representations are offered.
- **Video, audio, PDFs, archives, or any other files:** Copy files in the file
  manager, then press the shortcut. A single file retains its extension and type.
  Multiple files upload separately and copy one URL per line. Files are copied,
  never moved, even when the clipboard contains a file-manager cut operation.
- **Text / Markdown:** Preview the text and select Plain text or Markdown. Most
  editors put Markdown on the clipboard as plain text, so choose Markdown in the
  dialog when needed. The full content is uploaded; the preview shows at most
  4 KiB. Rich browser selections default to plain text when available.
- **Other MIME data:** Upload the offered bytes with a matching extension when
  known, or `.bin` otherwise. Internal-only clipboard formats are skipped.

Markdown is uploaded as a Markdown file rather than rendered into a hosted page.
Copied web links are uploaded as text; their contents are not downloaded.

The clipboard is snapshotted into a private temporary directory before confirmation
and deleted when the app exits normally. Large files stream from disk for upload.
Filenames get a timestamp and random suffix so repeated uploads do not overwrite one another.
The single-object upload limit is 5 GiB. Zip folders before copying them. Remote
file URIs are rejected; copied HTTP links upload as text when offered as plain text.

Uploads run in the background while the dialog shows progress. Repeated shortcut
presses do not start duplicate windows. Cancel and upload failures preserve the
clipboard. If a batch partially fails, already uploaded URLs are shown in the error
dialog; successful remote objects are kept. If copying the URL fails, it is shown
for manual copying. Uploading is committed once you click Upload.

Objects retain their content types, including HTML and SVG. Use a sharing domain
appropriate for content you intend to serve publicly.

## Commands

If `~/.local/bin` is in your `PATH`, use the commands below. Otherwise, replace
`simple-uploader` with `~/.local/bin/simple-uploader`.

```bash
simple-uploader                  # read, confirm, upload, copy URL
simple-uploader --setup          # bucket settings
simple-uploader --setup-shortcut # register Ctrl+Shift+Alt+U
simple-uploader --check          # dependency/config check; no upload
simple-uploader --version
simple-uploader --config /path/to/s3.conf
```

`--check` validates local configuration and dependencies. It does not upload
anything or test credentials against your storage provider.

## Troubleshooting

**The shortcut does nothing:** launch `~/.local/bin/simple-uploader` from a
terminal to see any error, then rerun `--setup-shortcut`. If another app owns
`Ctrl+Shift+Alt+U`, choose a different combination in desktop keyboard settings.

**Missing GTK or clipboard tools:** install the dependencies in the install
section. The launcher uses the system Python at `/usr/bin/python3`, so install
PyGObject through your distribution's package manager.

**Upload fails with HTTP 403 or a signature error:** check the API endpoint,
bucket, signing region, credentials, and token permissions. R2 needs a blank ACL.

**Upload succeeds, but the link is inaccessible:** check public read access and
`S3_PUBLIC_URL_BASE`. For R2, use your public custom domain or enabled development
URL rather than the S3 API endpoint.

## Update

From your checkout:

```bash
git pull --ff-only
./install.sh
```

Your bucket configuration is stored separately and is preserved.

## Development

Source checkouts can run `./src/simple-uploader`. Run the test suite with:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

To include GTK confirmation, cancellation, error, and multiple-file tests from a
graphical desktop session:

```bash
SIMPLE_UPLOADER_UI_TESTS=1 PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Tests use a local HTTP server that verifies S3 request signatures and an isolated
test clipboard. They do not use real storage credentials or replace your desktop
clipboard.

### Build a Debian package

```bash
bash build.sh 1.0.0
sudo apt install ./dist/simple-uploader_1.0.0_all.deb
/usr/bin/simple-uploader --setup-shortcut
/usr/bin/simple-uploader --setup
```

The Debian package installs commands under `/usr/bin`. Run shortcut setup as your
desktop user after installing. Custom source-install prefixes are also supported:
`PREFIX=/your/prefix ./install.sh --no-shortcut` with appropriate permissions.

## Uninstall

For the default per-user installation:

```bash
rm ~/.local/bin/simple-uploader
rm -r ~/.local/lib/simple-uploader
rm ~/.local/share/applications/simple-uploader.desktop
```

Remove **Simple Uploader** from your desktop's custom keyboard shortcuts.
Your bucket configuration and installed clipboard helpers are retained.
For a Debian package installation, use `sudo apt remove simple-uploader`.
