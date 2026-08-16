# Super Mario Bros. 3 Setup Guide

## Required Software

- [Archipelago](https://github.com/ArchipelagoMW/Archipelago/releases)
- The SMB3 apworld (`smb3.apworld`) — **download the latest `smb3.apworld` from the
  [Releases page](https://github.com/shiro-gure/smb3ap/releases)** and drop it into your
  Archipelago `custom_worlds` folder (Windows: `C:\ProgramData\Archipelago\custom_worlds\`),
  then restart the launcher/client. No building required.
- A legally obtained **Super Mario Bros. 3 (USA) (Rev 1)** ROM — the **PRG1 / Rev A** revision. No ROM is distributed.
- [BizHawk](https://tasvideos.org/BizHawk/ReleaseHistory) 2.9 or later (2.10 recommended).

### Configuring BizHawk

Once you have installed BizHawk, open `EmuHawk.exe` and change the following settings:

- Go to `Config > Customize`. On the **Advanced** tab, set the Lua Core to **`Lua+LuaInterface`**
  (not `NLua+KopiLua`/NLua), then restart EmuHawk. The generic connector requires this core.
- Under `Config > Customize`, check the **"Run in background"** option so you don't disconnect from the client while
  tabbed out.
- Open any `.nes` file, then go to `Config > Controllers…` to configure your inputs.

## Generating and Patching a Game

1. Create your options file (YAML). You can make one on the
   [Super Mario Bros. 3 options page](../../../games/Super%20Mario%20Bros.%203/player-options).
2. Point Archipelago at your ROM so the patched (checkmark) ROM can be built. In your Archipelago `host.yaml`, set:
   ```yaml
   smb3_options:
     rom_file: "Super Mario Bros. 3 (USA) (Rev 1).nes"
   ```
   (Use the full path, or place the ROM in the Archipelago folder. It must be the PRG1 / Rev 1 revision — a mismatched
   ROM is rejected during generation.)
3. Follow the general Archipelago instructions for
   [generating a game](../../Archipelago/setup/en#generating-a-game). Your patch file will have the `.apsmb3` extension.
4. Open `ArchipelagoLauncher.exe`.
5. Select **"Open Patch"** on the left and choose your `.apsmb3` file.
6. If prompted, locate your vanilla PRG1 ROM. A patched `.nes` is created next to the patch file.
7. On first use with BizHawk Client, you'll also be asked to locate `EmuHawk.exe` in your BizHawk install.

If your generated seed contains no `.apsmb3`, generation couldn't find your ROM — set `smb3_options.rom_file` in
`host.yaml` (step 2) and regenerate. The client log will note when the patch was skipped for this reason.

## Connecting to a Server

Opening a patch file usually does steps 1–5 for you automatically. Keep them in mind in case you have to reopen a
window mid-game.

1. Super Mario Bros. 3 uses Archipelago's **BizHawk Client**. If it isn't still open from patching, re-open it from the
   launcher.
2. Ensure EmuHawk is running the patched ROM.
3. In EmuHawk, go to `Tools > Lua Console`. This window must stay open while playing.
4. In the Lua Console, go to `Script > Open Script…`.
5. Navigate to your Archipelago install folder and open `data/lua/connector_bizhawk_generic.lua`.
   Use the copy in *that machine's own* Archipelago install — it needs its sibling `lua_5_3_compat.lua`.
6. The emulator and client will connect. The BizHawk Client window should indicate it connected and recognized
   Super Mario Bros. 3 (look for the `CLIENT_REV` build stamp).
7. To connect to the server, enter your room's address and port (e.g. `archipelago.gg:38281`) into the top text field
   of the client and click Connect. Enter your slot name if prompted.

You should now be able to send checks (clear airships and fortresses) and receive items. These steps can be repeated to
reconnect at any time; progress re-syncs on reconnect.
