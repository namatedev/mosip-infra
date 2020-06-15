import subprocess
import os
import logging
import time
import sys
from common import *
from config import *
import base64
import ldap.modlist as modlist 
import ldap

logger = logging.getLogger(__name__)

def create_context_entry(partition_name):
    '''
    Context template is generated by stringfying this:
    dn: c=<country_name>
    c: <country_name> 
    objectclass: domain
    objectclass: top
    dc: <country_name> 
    '''
    template = 'dn: c=%s\nc: %s\nobjectclass: domain\nobjectclass: top\ndc: %s'
    pn = partition_name
    ce = template % (pn, pn, pn)
    b = base64.b64encode(bytes(ce, 'utf-8'))  # bytes type
    return b.decode()  # Convert bytes to str 

def restart_apacheds():
    command('sudo /opt/apacheds-2.0.0.AM25/bin/apacheds restart default')
    time.sleep(10.0)  # Need to wait for server to start. TODO make this better

def install_apacheds(): 
    command('wget http://mirrors.estointernet.in/apache//directory/apacheds/dist/2.0.0.AM25/apacheds-2.0.0.AM25-64bit.bin')
    command('chmod 755 apacheds-2.0.0.AM25-64bit.bin')
    command('sudo useradd -M apacheds') 
    command('sudo ./apacheds-2.0.0.AM25-64bit.bin')
    command('sudo yum -y install openldap-clients')
    command('sudo yum -y install openldap-devel')
    restart_apacheds()

def load_ldap(partition_name):
    create_partition(partition_name) 
    modify_ssha_algo('SSHA-256')  # Default is SSHA
    load_schema()
    load_data()
   
def load_schema():
    logger.info('Loading schema')
    command('ldapmodify -h localhost -p 10389 -D "uid=admin,ou=system" -w "secret" -a -f ./resources/ldap/mosip-schema-extn.ldif')

def load_data():
    logger.info('Loading with sample data')
    command('ldapmodify -h localhost -p 10389 -D "uid=admin,ou=system" -w "secret" -a -f ./resources/ldap/mosip-entries.ldif')

    restart_apacheds()

def create_partition(partition_name): 
    logger.info('Creating partition for %s' % partition_name)
    s = open('./resources/ldap/partition_template.ldif').read()
    s = s.replace('[partition_name]', partition_name)
    context_entry = create_context_entry(partition_name) 
    s = s.replace('[context_entry]', context_entry)
    ldif = '/tmp/partition.ldif'
    f = open(ldif, 'wt')
    f.write(s) 
    f.close()
    command('ldapmodify -h localhost -p 10389 -D "uid=admin,ou=system" -w "secret" -a -f %s' % ldif)
    restart_apacheds()

def add_user_in_ldap(user_info, ld):
    '''
    Adds entry into LDAP. Note that if the DN already exists the skipped 
    meaning update does not take place.
    TODO: Update records if anything changes

    Args:
        ld: ldap connection 
        user_info:  UserInfo structure in common.py 
    '''
    u = user_info
    dn = 'uid=%s,ou=people,c=%s' % (u.uid, u.country)
    attrs = {}
    attrs['objectClass'] = [b'userDetails', b'top', b'person', b'organizationalPerson', b'inetOrgPerson']
    attrs['cn'] = [u.user_name.encode()]
    attrs['sn'] = [u.user_name.encode()]
    attrs['userPassword'] = [u.user_password.encode()]
    attrs['mail'] = [u.user_email.encode()]
    attrs['mobile'] = [u.user_mobile.encode()]
    
    ldif = modlist.addModlist(attrs)
    ld.add_s(dn, ldif)

def add_role_in_ldap(role, country, ld):
    dn = 'cn=%s,ou=roles,c=%s' % (role, country)
    attrs = {}
    attrs['objectClass'] = [b'top', b'organizationalRole']
    attrs['cn'] = [role.encode()]
    
    ldif = modlist.addModlist(attrs)
    ld.add_s(dn, ldif)

def add_user_to_role(uid, role, ld, country):
    '''
    Args:
        uid: As in LDAP
        role: str
        ld: LDAP connection
    '''
    dn = 'cn=%s,ou=roles,c=%s' % (role, country)
    attrs = {}
    attrs['changetype'] = [b'modify']
    attrs['add'] = [b'roleOccupant']
    s = 'uid=%s,ou=people,c=%s' % (uid, country)
    attrs['roleOccupant'] = [s.encode()]
    s = 'uid=%s,ou=people,c=%s' % (uid, country)
    t = [(ldap.MOD_ADD, 'roleOccupant', s.encode())]

    ld.modify_s(dn, t) 

def modify_ssha_algo(algo):
    '''
    Args:
        algo: str like 'SSHA', 'SSHA-256' etc.
        ld: LDAP connection
    '''
    ld = ldap.initialize('ldap://localhost:%d' % LDAP_PORT)
    ld.bind_s('uid=admin,ou=system', 'secret')

    dn = 'ads-interceptorId=passwordHashingInterceptor,ou=interceptors,ads-directoryServiceId=default,ou=config'
    attrs = {} 
    attrs['changetype'] = [b'modify']
    t = [(ldap.MOD_REPLACE, 'ads-hashalgorithm',  algo.encode())]
    ld.modify_s(dn, t)

    ld.unbind_s()

