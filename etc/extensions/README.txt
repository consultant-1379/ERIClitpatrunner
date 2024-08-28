Any "*.conf" files in the "etc/extensions" directory will be included in the
RPM, and installed in /opt/ericsson/nms/litp/etc/extensions.  This behaviour
is triggered by the existence of this README.txt file; deleting or renaming
this file will mean that files in "etc/extensions" are no longer included in
the RPM.
