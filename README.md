# rMview: a fast live viewer for reMarkable

![screenshot](https://raw.githubusercontent.com/bordaigorl/rmview/master/screenshot.png)

## Choose your flavour

There are two versions of rMview, presenting the same interface but using different back-ends (thus requiring different setups on the reMarkable):

* The "reStreamer-like" version, in the `master` branch
* The "VNC-based" version, in the `vnc` branch

In my tests, the VNC version is a clear winner, but it has different requirements, so I am keeping both alive for the moment.

**Volunteers wanted**: if you have experience with build systems/packaging for python, and/or experience in producing bundles with pyQt, and feel like contributing to the project, drop me a line!

## Instructions

To run the program you need python with pyqt5 installed.
Before running the program the first time, generate the resource file with

    pyrcc5 -o src/resources.py resources.qrc 

Then you can invoke the program with

    python src/rmview.py [config]

the optional `config` parameter is the filename of a json configuration file.
If the parameter is not found, the program will look for a `rmview.json` file in the current directory, or, if not found, for the path stored in the environment variable `RMVIEW_CONF`.
If none are found, or if the configuration is underspecified, the tool is going to prompt for address/password.

The supported configuration settings are:

```js
{ // all settings are optional, comments not allowed
  "ssh": {
    "address": "10.11.99.1", // works over WiFi too!
    "username": "root",
    "key": "~/.ssh/id_rsa_remarkable",
    // alternatively to key, "password": "****" is supported
    "timeout": 1 // in seconds
  },
  "orientation": "portrait", // default: landscape
  "pen_size": 10, // set to 0 to disable
  "pen_color": "red",
  "background_color": "black", // default: white
  "fetch_frame_delay": 0.03 // sleep 0.03s on remarkable before fetching new frame (default is no delay)
  "lz4_path_on_remarkable": "/usr/opt/lz4" // default: $HOME/lz4
}
```

Tested with Python 3.8.2, PyQt 5.14.2, MacOs 10.15.4, reMarkable firmware 2.1.1.3

## Requirements

### On your computer:

- Python 3
- PyQt5
- Paramiko
- lz4framed for `master` branch
- Twisted for `vnc` branch

They can be installed via `pip install pyqt5 paramiko py-lz4framed`.
If you use Anaconda, please install the dependencies via `conda` (and not `pip`).

### On the reMarkable:

*"reStreamer-like" version:*

- LZ4, installed by running `scp lz4.arm.static <REMARKABLE>:lz4`.
  Make sure `lz4` is executable by running `ssh <REMARKABLE> chmod +x lz4`.

*"VNC-based" version:*

- Install [rM-vnc-server][vnc] and its dependency [mxc_epdc_fb_damage](https://github.com/peter-sa/mxc_epdc_fb_damage). Instructions can be found in the [wiki](https://github.com/bordaigorl/rmview/wiki/How-to-run-the-VNC-based-version).

## To Do

 - [ ] Settings dialog
 - [ ] About dialog
 - [ ] Pause stream of screen/pen
 - [ ] Build system
 - [ ] Bundle
 - [ ] Add interaction for Lamy button? (1 331 1 down, 1 331 0 up)
 - [ ] Remove dependency to Twisted in `vnc` branch


## Credits

I took inspiration from the following projects:

- [QtImageViewer](https://github.com/marcel-goldschen-ohm/PyQtImageViewer/)
- [remarkable_mouse](https://github.com/Evidlo/remarkable_mouse/)
- [reStream](https://github.com/rien/reStream)
- [rM-vnc-server](https://github.com/peter-sa/rM-vnc-server)
- [VNC client](https://github.com/sibson/vncdotool) originally written by Chris Liechti

Icons adapted from designs by Freepik, xnimrodx from www.flaticon.com


## Disclaimer

This project is not affiliated to, nor endorsed by, [reMarkable AS](https://remarkable.com/).
**I assume no responsibility for any damage done to your device due to the use of this software.**

## Licence

GPLv3

[vnc]: https://github.com/peter-sa/rM-vnc-server