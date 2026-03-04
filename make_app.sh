#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# make_app.sh  –  Build "Subnet Calculator.app" in the current directory
#
# Run once (or after any source change):
#   bash make_app.sh
#
# What it does:
#   1. Generates icon_1024.png via create_icon.py (pure Python, no deps)
#   2. Creates a macOS .iconset from that PNG using sips
#   3. Compiles the iconset to a .icns file with iconutil
#   4. Assembles a standard .app bundle (Contents/MacOS + Contents/Resources)
#   5. Writes Info.plist with the correct CFBundle keys
#   6. Creates a launcher stub that runs the bundled Python script
# ─────────────────────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Subnet Calculator"
APP_DIR="$SCRIPT_DIR/$APP_NAME.app"
CONTENTS="$APP_DIR/Contents"
MACOS="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"

echo ""
echo "═══════════════════════════════════════════"
echo "  Building $APP_NAME.app"
echo "═══════════════════════════════════════════"

# ── 1. Generate the icon ──────────────────────────────────────────────────────
echo ""
echo "▶ Generating icon…"
/usr/bin/python3 "$SCRIPT_DIR/create_icon.py"

PNG_1024="$SCRIPT_DIR/icon_1024.png"
if [ ! -f "$PNG_1024" ]; then
  echo "  ERROR: icon_1024.png was not created."
    exit 1
fi

# ── 2. Build iconset from the 1024-px PNG ────────────────────────────────────
echo "▶ Building iconset…"
ICONSET="$SCRIPT_DIR/SubnetCalc.iconset"
rm -rf "$ICONSET"
mkdir -p "$ICONSET"

# sips resizes from the base 1024-px PNG to each required size
sips -z 16   16   "$PNG_1024" --out "$ICONSET/icon_16x16.png"        > /dev/null
sips -z 32   32   "$PNG_1024" --out "$ICONSET/icon_16x16@2x.png"     > /dev/null
sips -z 32   32   "$PNG_1024" --out "$ICONSET/icon_32x32.png"        > /dev/null
sips -z 64   64   "$PNG_1024" --out "$ICONSET/icon_32x32@2x.png"     > /dev/null
sips -z 128  128  "$PNG_1024" --out "$ICONSET/icon_128x128.png"      > /dev/null
sips -z 256  256  "$PNG_1024" --out "$ICONSET/icon_128x128@2x.png"   > /dev/null
sips -z 256  256  "$PNG_1024" --out "$ICONSET/icon_256x256.png"      > /dev/null
sips -z 512  512  "$PNG_1024" --out "$ICONSET/icon_256x256@2x.png"   > /dev/null
sips -z 512  512  "$PNG_1024" --out "$ICONSET/icon_512x512.png"      > /dev/null
cp   "$PNG_1024"              "$ICONSET/icon_512x512@2x.png"

# ── 3. Compile to .icns ───────────────────────────────────────────────────────
echo "▶ Compiling .icns…"
ICNS="$SCRIPT_DIR/SubnetCalc.icns"
iconutil -c icns "$ICONSET" -o "$ICNS"
rm -rf "$ICONSET"          # clean up temporary iconset
rm -f  "$PNG_1024"         # clean up intermediate PNG
rm -f  "$SCRIPT_DIR/icon_512.png"

# ── 4. Assemble .app bundle ───────────────────────────────────────────────────
echo "▶ Assembling app bundle…"
rm -rf "$APP_DIR"
mkdir -p "$MACOS" "$RESOURCES"

# Copy source files into Resources
cp "$SCRIPT_DIR/subnet_calculator.py" "$RESOURCES/"
cp "$ICNS" "$RESOURCES/SubnetCalc.icns"

# ── 5. Info.plist ─────────────────────────────────────────────────────────────
cat > "$CONTENTS/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>             <string>Subnet Calculator</string>
  <key>CFBundleDisplayName</key>      <string>Subnet Calculator</string>
  <key>CFBundleExecutable</key>       <string>Subnet Calculator</string>
  <key>CFBundleIdentifier</key>       <string>com.local.subnet-calculator</string>
  <key>CFBundleVersion</key>          <string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key>      <string>APPL</string>
  <key>CFBundleIconFile</key>         <string>SubnetCalc</string>
  <key>LSMinimumSystemVersion</key>   <string>11.0</string>
  <key>NSHighResolutionCapable</key>  <true/>
  <key>LSUIElement</key>              <true/>
</dict>
</plist>
PLIST

# ── 6. Launcher stub ─────────────────────────────────────────────────────────
LAUNCHER="$MACOS/$APP_NAME"
cat > "$LAUNCHER" << 'LAUNCHER'
#!/bin/bash
RESOURCES="$(dirname "$0")/../Resources"
exec /usr/bin/python3 "$RESOURCES/subnet_calculator.py"
LAUNCHER
chmod +x "$LAUNCHER"

# ── Tidy up .icns from project root (it's now inside the bundle) ─────────────
rm -f "$ICNS"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════"
echo "  ✓  Built:  $APP_DIR"
echo "═══════════════════════════════════════════"
echo ""
echo "  Double-click to launch, or run directly:"
echo "    /usr/bin/python3 '$SCRIPT_DIR/subnet_calculator.py'"
echo ""
echo "  To install system-wide:"
echo "    cp -r '$APP_NAME.app' /Applications/"
echo “"