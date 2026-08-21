# The Sims 4 Index ("Simdex")
The Sims Index ("Simdex") is an open-source project that allows mod creators to create modpacks and/or attach detailed metadata to their own mods or modpacks. This software invents a new file format (Sims 4 Index file or `.s4i`) which can be imported into the app in order to be installed as a mod/modpack.

Sims 4 Index files and the Simdex app exist to create, not only an easier Sims 4 modding experience by removing the process of manual installs and sorting, but also to allow mod developers to attach metadata (icon, name, author, short desc, long desc, etc.) to their mods.

## What does Simdex actually do?
Fundamentally, we change three factors of Sims 4 modding:
* Players no longer have to manually install mods/CC by dropping them into `Mods` or `Tray`
* Mod creators can take more ownership over their mods beyond what Sims 4 standardly supports
* We allow the creation of a new format of modding for Sims 4: modpacks. These function as a collection of existing mods and can be installed and managed as one thing.

## How does it work?
I developed both an [app](https://simdex.vercel.app/download) and a [website](https://simdex.vercel.app/) to manage this ambitious system. The app is windows-only for now (I'd be grateful for other programmers to both contact me and help me out: gumpaperdev@gmail.com). Users can look through the index of available Simdex-compatible mods on the website's landing page and look through their information as well as (optionally) download them.

Additionally, via the site, you can download the app itself. This app allows players/developers to actually install mods/modpacks. To clarify, "download" and "install" are two very different concepts for this project: to download a mod/modpack means to obtain the s4i file. To install means to have the app extract the contents of the mod/modpack and install it into your Mods/Tray folder as well as track it in our system for future management (such as uninstalling the mod/modpack directly from the app, enabling/disabling a mod/modpack **without** uninstalling them, etc.).

The app, however, also has separate functions for mod developers: it hosts a Creator panel. (which you need to sign up for an account for just so we can save your project metadata and display it on the website.) On said creator panel, mod developers can create new items known as "Projects". A Project is a term for either a mod or a modpack which can be installed by Simdex. We use one term to avoid having to repeat "mod/modpack". Projects are only a file layout and metadata, actual mod development still happen wherever the mod developer sees fit. They can simply create a new project, import their mod's files (`.package`, `.ts4script`, `.trayitem`, etc.) into the project, and edit the Project's metadata. Our modpacks, however, **only** allow `.s4i` mods to into them.

After that, they can save their mod and publish it to Simdex. Publishing doesn't automatically add a mod to Simdex, however. Our staff team (aka just me, bahaha) personally vet each mod at a minimal level (read ToS for information on the vetting process, if you like). Once your mod is vetting, it'll either get approved or rejected. If approved, you can finally package your mod as a `.s4i` file and edit your approved project so it's metadata links back to your mod's file. It is **VERY** worthy to note, Simdex doesn't personally store `.s4i` files, only their metadata. Mod developers can still link their actual pages to download and/or purchase their project (i.e., Patreon or the likeness).

## Notes
* Mod developers: when publishing a project, you aren't expected to have a download link for an `.s4i` file. Publish the project under a download link for your project's folder (located at C:\Users\[YOUR-USERNAME]\AppData\Roaming\vergiesdiary\SimdexWindows\Projects\[PROJECT-NAME]). Invalid entries will be rejected. After it is approved, you can edit the project from the Approved Projects panel and change the download link to one linking to your `.s4i` file.
* Mod developers: modpacks explicitly require permission/licensing for redistributed third-party content. It is also suggested you credit each mod creator appropriately. Please respect creators and their effort. 
* Players: a verified developer on Simdex does **NOT** indicate that they are a trustworthy individual, it simply means they took the time to verify the email they signed up for their account with. You can publish mods/modpacks to Simdex with or without a verified email.
* All: since Simdex is managed by me alone right now, the staff team might take long periods to address emails or concerns.
* All: the team behind this project is called VergiesDiary.
* All: you can report bugs, **Simdex** creators, or other stuff to the team's email vergiesdiary@gmail.com. Suggestions and general inquiries are also greatly appreciated.
* All: in the app, there are guides made to help you navigate it.