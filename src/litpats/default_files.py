default_file_list = [
    'etc/puppet/modules/cmw/files/ERIC-opendj-CXP_1234567_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/ERIC-opendj-I-CXP_1234567_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/ERIC-jbosseap-CXP_1234567_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/ERIC-jbosseap-I2-CXP_1234567_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/ERIC-jbosseap-I4-CXP_1234567_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/ERIC-examplelog-CXP123456_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/ERIC-examplelog-I2-CXP123456_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/ERIC-examplelog-I4-CXP123456_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/LITPApp1-CXP12345_1-R1A01-1.noarch.rpm',
    'etc/puppet/modules/cmw/files/3PP-LITPApp1-CXP123456_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/3PP-LITPApp1-InstCamp-R1A01.sdp',
    'etc/puppet/modules/cmw/files/COM-CXP9017585_2.sdp',
    'etc/puppet/modules/cmw/files/ERIC-COM-I-TEMPLATE-CXP9017585_2-R6A02.sdp',
    'etc/puppet/modules/cmw/files/COM_SA-CXP9017697_3.sdp',
    'etc/puppet/modules/cmw/files/ERIC-ComSaInstall.sdp',
    'etc/puppet/modules/cmw/files/ERIC-JAVAOAM-CXP9019839_1-R2B09.sdp',
    'etc/puppet/modules/cmw/files/ERIC-JAVAOAM-I-2SCxNPL.sdp',
    'etc/puppet/modules/cmw/files/3PP-jbosseap-CXP9022745_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/3PP-jbosseap-I2-CXP9022745_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/3PP-jbosseap-I4-CXP9022745_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/3PP-opendj-CXP9022742_1-R1A01.sdp',
    'etc/puppet/modules/cmw/files/3PP-opendj-I-CXP9022742_1-R1A01.sdp',
]


def create(root_path, fileclass):
    return dict(
        [("%s/%s" % (root_path, path), fileclass())
                for path in default_file_list]
    )
