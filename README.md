# rMview: a fast live viewer for reMarkable 1

[![Demo](https://raw.githubusercontent.com/bordaigorl/rmview/vnc/screenshot.png)][demo]


## Features

* Demo [:rocket: here][demo]
* Fast streaming of the screen of your reMarkable 1 to a window in your computer
* UI for zooming, panning, rotating
* Pen tracking: a pointer follows the position of the pen when hovering on the reMarkable
* Clone a frame into separate window for reference
* Save screenshots as PNG

> :warning: **WARNING** :warning::
> rMview supports **reMarkable 1 only**, see [this issue](https://github.com/bordaigorl/rmview/issues/22).
> Support for reMarkable 2 may come once it gets wider diffusion and a reliable method to stream the framebuffer data is found.


> :loudspeaker: **Volunteers needed**: if you have experience with producing binary bundles with pyQt, and feel like contributing to the project, drop me a line!


## Installation

1. You will need [Python3][py3] on your computer.

   > :warning: Please make sure `pip` is pointing to the Python3 version if your system has Python2 as well.
   If not, use `pip3` instead of `pip` in what follows.

2. The easiest installation method is by using pip:

       pip install .

   which will install all required dependencies and install a new `rmview` command.
   Alternatively you may want to install the dependencies ([PyQt5][pyqt5], [Paramiko][paramiko], [Twisted][twisted]) with `pip` manually.


3. On the reMarkable itself you need to install the standalone version of [rM-vnc-server][vnc].
   Instructions can be found in the [wiki](https://github.com/bordaigorl/rmview/wiki/How-to-run-the-VNC-based-version).
   This last step will be automated in the near future.

To run the tool after installation just run `rmview` from a console.

> :warning: **WARNING** :warning::
> If you use [Anaconda][anaconda], please install the dependencies via `conda` (and not `pip`) then run `pip install .`.

Tested with Python 3.8.2, PyQt 5.14.2, MacOs 10.15.4, reMarkable firmware 2.1.1.3.

## Usage and configuration

**Suggested first use:**
after installing run `rmview`, insert when prompted the IP of your tablet and the password,
as found in the <kbd>Menu / Settings / Help / Copyright and Licences</kbd> menu of the tablet.
Then, optionally, select "Settings..." from the context menu (or the error dialog) to open
the default configuration file which you can edit according to the documentation below.

More generally, you can invoke the program with

    rmview [config]

the optional `config` parameter is the filename of a json configuration file.
If the parameter is not found, the program will look for a `rmview.json` file in the current directory, or, if not found, for the path stored in the environment variable `RMVIEW_CONF`.
If none are found, or if the configuration is underspecified, the tool is going to prompt for address/password.

### Configuration files

The supported configuration settings are below.
Look in file `example.json` for an example configuration.
All the settings are optional.

| Setting key              | Values                                                  | Default       |
| ------------------------ | ------------------------------------------------------- | ------------- |
| `ssh`                    | Connection parameters (see below)                       | `{}`          |
| `orientation`            | `"landscape"`, `"portrait"`, `"auto"`                   | `"landscape"` |
| `pen_size`               | diameter of pointer in px                               | `15`          |
| `pen_color`              | color of pointer and trail                              | `"red"`       |
| `pen_trail`              | persistence of trail in ms                              | `200`         |
| `background_color`       | color of window                                         | `"white"`     |
| `hide_pen_on_press`      | if true, the pointer is hidden while writing            | `true`        |
| `show_pen_on_lift`       | if true, the pointer is shown when lifting the pen      | `true`        |


Connection parameters are provided as a dictionary with the following keys (all optional):

| Parameter                | Values                                 | Comments                              |
| ------------------------ | -------------------------------------- | ------------------------------------- |
| `address`                | IP of remarkable                       | tool prompts for it if missing        |
| `auth_method`            | Either `"password"` or `"key"`         | defaults to password if key not given |
| `username`               | Username for ssh access on reMarkable  | default: `"root"`                     |
| `password`               | Password provided by reMarkable        | not needed if key provided            |
| `key`                    | Local path to key for ssh              | not needed if password provided       |
| `timeout`                | Connection timeout in seconds          | default: 1                            |
| `insecure_auto_add_host` | Ignores the check on the fingerprint   | default: `false`                      |

The `address` parameter can be either:
- a single string, in which case the address is used for connection
- a list of strings, which will be presented at launch for selection

To establish a connection with the tablet, you can use any of the following:
- Leave `auth_method`, `password` and `key` unspecified: this will ask for a password
- Specify `"auth_method": "key"` to use a SSH key. In case an SSH key hasn't already been associated with the tablet, you can provide its path with the `key` setting.
- Provide a `password` in settings


If `auth_method` is `password` but no password is specified, then the tool will ask for the password on connection.


:warning: **Connecting after an update:**
An update to the reMarkable tablet would change its "fingerprint" i.e. the identifier that signals we are connecting to the expected device (and not somebody impersonating it).
When this happens you may get an error message upon connection.
There are two main ways to fix this:
 1. Change your `~/.ssh/known_hosts` file to match the new fingerprint (you can get instructions by connecting manually via ssh).
 2. Set the `insecure_auto_add_host` setting to `true`, which will make rmview ignore the check.
    This is not recommended unless you are in a trusted network.

:warning: **Key format error:**
If you get an error when connect using a key, but the key seems ok when connecting manually with ssh, you probably need to convert the key to the PEM format (or re-generate it using the `-m PEM` option of `ssh-keygen`). See [here](https://github.com/paramiko/paramiko/issues/340#issuecomment-492448662) for details.


## To Do

 - [ ] Settings dialog
 - [ ] About dialog
 - [ ] Pause stream of screen/pen
 - [ ] Binary bundles for Window, Linux and MacOs (PyInstaller?)
 - [ ] Add interaction for Lamy button? (1 331 1 down, 1 331 0 up)
 - [ ] Remove dependency to Twisted in `vnc` branch


## Legacy reStreamer-like version

There are two versions of rMview, presenting the same interface but using different back-ends (thus requiring different setups on the reMarkable):

* The "VNC-based" version, in the [`vnc` branch][vnc-branch] (default)
* The "reStreamer-like" version, in the [`ssh` branch][ssh-branch]

In my tests, the VNC version is a clear winner.
The `ssh` branch of this repo hosts the reStreamer-like version for those who prefer it, but I am not planning to update it.


## Credits

I took inspiration from the following projects:

- [QtImageViewer](https://github.com/marcel-goldschen-ohm/PyQtImageViewer/)
- [remarkable_mouse](https://github.com/Evidlo/remarkable_mouse/)
- [reStream](https://github.com/rien/reStream)
- [rM-vnc-server](https://github.com/pl-semiotics/rM-vnc-server)
- [VNC client](https://github.com/sibson/vncdotool) originally written by Chris Liechti

Icons adapted from designs by Freepik, xnimrodx from www.flaticon.com

Thanks to @adem amd @ChrisPattison for their [PRs](https://github.com/bordaigorl/rmview/issues?q=is%3Apr+is%3Aclosed).

## Disclaimer

This project is not affiliated to, nor endorsed by, [reMarkable AS](https://remarkable.com/).
**I assume no responsibility for any damage done to your device due to the use of this software.**

## Licence

GPLv3

[vnc]: https://github.com/pl-semiotics/rM-vnc-server
[demo]: https://www.reddit.com/r/RemarkableTablet/comments/gtjrqt/rmview_now_with_support_for_vnc/
[ssh-branch]: https://github.com/bordaigorl/rmview/tree/ssh
[vnc-branch]: https://github.com/bordaigorl/rmview/tree/vnc

[py3]: https://www.python.org/downloads/
[anaconda]: https://docs.anaconda.com/anaconda
[pyqt5]: https://www.riverbankcomputing.com/software/pyqt/
[paramiko]: http://www.paramiko.org/
[twisted]: https://twistedmatrix.com/trac/
