"""Fail closed on board execution identity, no privilege elevation."""
import os,pwd,sys
def require_nvidia():
    user=pwd.getpwnam('nvidia')
    ids=os.getresuid()
    gids=os.getresgid()
    if user.pw_uid==0 or ids!=(user.pw_uid,)*3 or gids!=(user.pw_gid,)*3:raise PermissionError('real/effective/saved uid/gid must all be nvidia, never root')
    return dict(user='nvidia',uid=ids,gid=gids,groups=os.getgroups(),pid=os.getpid())

def require_analysis_user():
    if os.geteuid()==0:raise PermissionError('analysis never runs as root')
    if sys.platform.startswith('linux'):return require_nvidia()
    return dict(user=pwd.getpwuid(os.geteuid()).pw_name,uid=os.geteuid(),scope='local offline analysis')
