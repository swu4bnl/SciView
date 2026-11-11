#!/usr/bin/env bash
# Manage the SciView entry in the user's application list: a .desktop entry on
# Linux or an app bundle in ~/Applications on macOS.
#
#   install_sciview_launcher_unix.sh                  ask, remember the answer, apply it
#   install_sciview_launcher_unix.sh --from-launcher  ask only when no answer is saved
#   install_sciview_launcher_unix.sh --add            remember "yes" and add the entry
#   install_sciview_launcher_unix.sh --remove         remember "no" and remove the entry
#
# This script is best effort. It never touches entries it did not create, it
# rewrites its own entry only when the content changed, and the launcher treats
# a non-zero exit as a warning rather than a reason to stop SciView.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ASSETS_DIR="$PROJECT_ROOT/src/sciview/interfaces/theme/assets"
APP_NAME="SciView"
APP_COMMENT="SciView X-ray scattering application"
SELF="scripts/$(basename "${BASH_SOURCE[0]}")"

read_pyproject_value() {
    # Print the first `key = "value"` line in pyproject.toml.
    sed -n "s/^$1 = \"\(.*\)\"\$/\1/p" "$PROJECT_ROOT/pyproject.toml" | head -n 1
}

APP_ID="$(read_pyproject_value app_id)"
APP_VERSION="$(read_pyproject_value version)"
if [[ -z "$APP_ID" || -z "$APP_VERSION" ]]; then
    echo "pyproject.toml must define 'version' and '[tool.sciview] app_id'." >&2
    exit 1
fi

PLATFORM="$(uname -s)"
case "$PLATFORM" in
    Linux)
        PLATFORM_KEY="linux"
        DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
        ENTRY_DESCRIPTION="the application menu"
        QUESTION="Add $APP_NAME to the application menu? [Y/n]"
        ;;
    Darwin)
        PLATFORM_KEY="macos"
        DATA_HOME="$HOME/Library/Application Support"
        ENTRY_DESCRIPTION="the Applications folder"
        QUESTION="Add $APP_NAME to your Applications folder? [Y/n]"
        ;;
    *)
        echo "Application-list registration is not supported on $PLATFORM."
        exit 0
        ;;
esac

# Same per-user data root the application uses for its session cache.
PREFERENCE_FILE="$DATA_HOME/sciview/launcher-shortcuts"
PREFERENCE_KEY="app_list"

# --- Saved answer --------------------------------------------------------------

read_preference() {
    [[ -f "$PREFERENCE_FILE" ]] || return 0
    sed -n "s/^$1=//p" "$PREFERENCE_FILE" | head -n 1
}

write_preference() {
    local other_lines=""
    if [[ -f "$PREFERENCE_FILE" ]]; then
        other_lines="$(grep -v "^$1=" "$PREFERENCE_FILE" || true)"
    fi
    mkdir -p "$(dirname "$PREFERENCE_FILE")" || return 1
    {
        if [[ -n "$other_lines" ]]; then
            printf '%s\n' "$other_lines"
        fi
        printf '%s=%s\n' "$1" "$2"
    } > "$PREFERENCE_FILE"
}

ask_yes_no() {
    # Usage: ask_yes_no "Question? [Y/n]" default-letter
    local answer
    read -r -p "$1 " answer || answer=""
    answer="${answer:-$2}"
    case "$answer" in
        [Yy]|[Yy][Ee][Ss]) return 0 ;;
        *) return 1 ;;
    esac
}

prompt_and_save() {
    local answer="no"
    if ask_yes_no "$QUESTION" y; then
        answer="yes"
    fi
    write_preference "$PREFERENCE_KEY" "$answer" || return 1
    echo "$APP_NAME remembers this answer. To change it, run $SELF --add or $SELF --remove."
}

# --- Linux -------------------------------------------------------------------

escape_desktop_string() {
    # Desktop Entry string values use backslash as the escape character.
    printf '%s' "${1//\\/\\\\}"
}

quote_desktop_exec() {
    # Exec arguments are quoted, with reserved characters backslash-escaped
    # inside the quotes, then string-escaped, then % doubled for field codes.
    local backtick='`'
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//\$/\\\$}"
    value="${value//$backtick/\\$backtick}"
    value="\"$value\""
    value="${value//\\/\\\\}"
    printf '%s' "${value//%/%%}"
}

linux_paths() {
    APPLICATIONS_DIR="$DATA_HOME/applications"
    ICON_DIR="$DATA_HOME/icons/hicolor/scalable/apps"
    DESKTOP_FILE="$APPLICATIONS_DIR/$APP_NAME.desktop"
    ICON_FILE="$ICON_DIR/sciview.svg"
}

entry_is_ours_linux() {
    linux_paths
    [[ -f "$DESKTOP_FILE" ]] || return 1
    local entry_root
    entry_root="$(sed -n 's/^X-SciView-Managed=//p' "$DESKTOP_FILE" | head -n 1)"
    [[ -n "$entry_root" && ( "$entry_root" == "$PROJECT_ROOT" || ! -e "$entry_root" ) ]]
}

install_linux() {
    linux_paths
    if [[ -e "$DESKTOP_FILE" ]] && ! entry_is_ours_linux; then
        echo "A $APP_NAME.desktop entry not created by this launcher exists at $DESKTOP_FILE; leaving it unchanged."
        return 0
    fi

    local content
    content="$(cat <<DESKTOP
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=$APP_COMMENT
Exec=env SCIVIEW_KEEP_SHELL_OPEN=1 $(quote_desktop_exec "$PROJECT_ROOT/Launch-SciView-linux.sh")
Path=$(escape_desktop_string "$PROJECT_ROOT")
Icon=$(escape_desktop_string "$ICON_FILE")
Terminal=true
Categories=Science;Education;
X-SciView-Managed=$PROJECT_ROOT
DESKTOP
)"

    if [[ -f "$DESKTOP_FILE" && -f "$ICON_FILE" && "$(cat "$DESKTOP_FILE")" == "$content" ]]; then
        return 0
    fi

    mkdir -p "$APPLICATIONS_DIR" "$ICON_DIR" || return 1
    cp "$ASSETS_DIR/sciview.svg" "$ICON_FILE" || return 1
    printf '%s\n' "$content" > "$DESKTOP_FILE" || return 1
    chmod 644 "$DESKTOP_FILE"
    echo "Added $APP_NAME to the application menu: $DESKTOP_FILE"
}

remove_linux() {
    entry_is_ours_linux || return 0
    rm -f "$DESKTOP_FILE" "$ICON_FILE" || return 1
    echo "Removed $APP_NAME from the application menu: $DESKTOP_FILE"
}

# --- macOS -------------------------------------------------------------------

macos_paths() {
    APP_BUNDLE="$HOME/Applications/$APP_NAME.app"
    CONTENTS_DIR="$APP_BUNDLE/Contents"
    RESOURCES_DIR="$CONTENTS_DIR/Resources"
    EXECUTABLE="$CONTENTS_DIR/MacOS/$APP_NAME"
    MARKER="$RESOURCES_DIR/sciview-project-root"
}

entry_is_ours_macos() {
    macos_paths
    [[ -f "$MARKER" ]] || return 1
    local entry_root
    entry_root="$(cat "$MARKER")"
    [[ -n "$entry_root" && ( "$entry_root" == "$PROJECT_ROOT" || ! -e "$entry_root" ) ]]
}

install_macos() {
    macos_paths
    if [[ -e "$APP_BUNDLE" ]] && ! entry_is_ours_macos; then
        echo "A $APP_NAME app not created by this launcher exists at $APP_BUNDLE; leaving it unchanged."
        return 0
    fi

    local plist
    plist="$(cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>$APP_ID</string>
    <key>CFBundleVersion</key>
    <string>$APP_VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$APP_VERSION</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundleIconFile</key>
    <string>sciview</string>
</dict>
</plist>
PLIST
)"

    # The bundle executable opens Terminal and runs the repository launcher, so
    # the user sees the same setup and update prompts as a double-clicked launch.
    local executable_script
    executable_script="$(cat <<'LAUNCHER'
#!/bin/sh
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cat "$SCRIPT_DIR/../Resources/sciview-project-root")"
/usr/bin/osascript \
    -e 'on run argv' \
    -e 'tell application "Terminal" to activate' \
    -e 'tell application "Terminal" to do script "cd " & quoted form of (item 1 of argv) & " && " & quoted form of (item 2 of argv)' \
    -e 'end run' \
    "$PROJECT_ROOT" "$PROJECT_ROOT/Launch-SciView-macOS.command"
LAUNCHER
)"

    if [[ -f "$MARKER" && "$(cat "$MARKER")" == "$PROJECT_ROOT" \
          && -f "$CONTENTS_DIR/Info.plist" && "$(cat "$CONTENTS_DIR/Info.plist")" == "$plist" \
          && -x "$EXECUTABLE" && "$(cat "$EXECUTABLE")" == "$executable_script" \
          && -f "$RESOURCES_DIR/sciview.icns" ]]; then
        return 0
    fi

    mkdir -p "$RESOURCES_DIR" "$CONTENTS_DIR/MacOS" || return 1
    cp "$ASSETS_DIR/sciview.icns" "$RESOURCES_DIR/sciview.icns" || return 1
    printf '%s\n' "$PROJECT_ROOT" > "$MARKER" || return 1
    printf '%s\n' "$plist" > "$CONTENTS_DIR/Info.plist" || return 1
    printf '%s\n' "$executable_script" > "$EXECUTABLE" || return 1
    chmod 755 "$EXECUTABLE" || return 1
    echo "Added $APP_NAME to ~/Applications: $APP_BUNDLE"
}

remove_macos() {
    entry_is_ours_macos || return 0
    rm -rf "$APP_BUNDLE" || return 1
    echo "Removed $APP_BUNDLE"
}

# --- Entry point -------------------------------------------------------------

entry_is_ours() { "entry_is_ours_$PLATFORM_KEY"; }
install_entry() { "install_$PLATFORM_KEY"; }
remove_entry() { "remove_$PLATFORM_KEY"; }

apply_preference() {
    case "$(read_preference "$PREFERENCE_KEY")" in
        yes) install_entry ;;
        no) remove_entry ;;
        *) return 0 ;;
    esac
}

case "${1:-}" in
    "")
        prompt_and_save || exit 1
        ;;
    --from-launcher)
        if [[ -z "$(read_preference "$PREFERENCE_KEY")" ]]; then
            if [[ -t 0 && -t 1 ]]; then
                prompt_and_save || exit 1
            else
                echo "Run $SELF to add $APP_NAME to $ENTRY_DESCRIPTION."
                exit 0
            fi
        fi
        ;;
    --add)
        write_preference "$PREFERENCE_KEY" yes || exit 1
        ;;
    --remove)
        if ! entry_is_ours; then
            echo "No $APP_NAME entry created by this launcher was found in $ENTRY_DESCRIPTION."
        fi
        write_preference "$PREFERENCE_KEY" no || exit 1
        ;;
    *)
        echo "Usage: $(basename "$0") [--from-launcher | --add | --remove]" >&2
        exit 2
        ;;
esac

apply_preference
