# SightingAssistant_Chatter Installation (Quick 5 Steps)

## 1. Verify dt CLI
Open PowerShell and run:

```powershell
dt gnai --help
```

If help output appears, continue.

## 2. Copy extension folder
Copy the entire `GNAI_AssisChatter` folder to the target PC.

## 3. Register native host
1. Open `chrome://extensions`.
2. Turn on Developer mode.
3. Load unpacked and select the `GNAI_AssisChatter` folder.
4. Copy the extension ID shown by Chrome.

Then run in PowerShell from `GNAI_AssisChatter\bridge`:

```powershell
.\install_native_host.ps1 -ExtensionId <YOUR_EXTENSION_ID> -Browser chrome
```

## 4. Reload extension
In `chrome://extensions`, click Reload for this extension (or restart Chrome).

## 5. Validate bridge connection
1. Open the side panel.
2. Click the gear icon (Settings) and select `連線測試`.

If it fails, start bridge manually once from `GNAI_AssisChatter\bridge`:

```powershell
.\run_bridge.ps1
```

Then run `連線測試` again.
