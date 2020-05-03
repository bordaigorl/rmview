# rMview: a fast live viewer for reMarkable

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
  "fetch_frame_delay": 0.03 // sleep 0.03s on remarkable before fetching new frame (default is no delay)
}
```

Tested with Python 3, PyQt 5.14.2, MacOs 10.15.4, reMarkable firmware 2.1.1.3

## Requirements

On your computer:

- Python 3
- PyQt5
- Paramiko
- lz4framed

They can be installed via `pip install pyqt5 paramiko py-lz4framed`.

On the reMarkable:

- lz4 which can be installed by running `scp lz4.arm.static <REMARKABLE>:lz4`.


## To Do

 - [ ] Settings dialog
 - [ ] About dialog
 - [ ] Pause stream of screen/pen
 - [ ] Action to spawn a static viewer on a frame
 - [ ] Build system
 - [ ] Bundle
 - [ ] Add interaction for Lamy button? (1 331 1 down, 1 331 0 up)


## Credits

I took inspiration from the following projects:

- [QtImageViewer](https://github.com/marcel-goldschen-ohm/PyQtImageViewer/)
- [remarkable_mouse](https://github.com/Evidlo/remarkable_mouse/)
- [reStream](https://github.com/rien/reStream)

Icons adapted from designs by Freepik, xnimrodx from www.flaticon.com

## Licence

GPLv3
