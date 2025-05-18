# MHWs EFX Template
EFX 010 template for Monster Hunter Wilds.

**UPDATE 5/18/2025**

Template structure rewritten. Now supports most efx files(7672/7676) for MHWs.

## EFX Color Change Script
![image](https://user-images.githubusercontent.com/46909075/232143830-d8a3bfac-7683-40b1-a830-99ce3a3a7e44.png)


![image](https://user-images.githubusercontent.com/46909075/213037217-9c32443a-156d-4b40-8204-98c98aaa8b95.png)

The **EFX_COLOR_CHANGE.1sc** script allows you to change the color of all entries in an EFX file. To use it, first install it under Scripts > View Install Scripts > Add.

Then with an EFX file open, run the script from the Scripts menu.

There are configurable options if you open the script file. You can enable or disable changing the colors of certain structs and also set the default colors.

The script is not intended to do all of the work. It will not work perfectly in all cases and you may have to manually tweak some things.

## Installation
Requires **[010 Editor](https://www.sweetscape.com/010editor/)**

Install the template under Templates > View Installed Templates > Add

## Test Template
Make sure 010 Editor Tools -> Options -> General -> Allow Only One Instance of 010 Editor is disabled
```bash
python BatchTemplateTest.py
```
