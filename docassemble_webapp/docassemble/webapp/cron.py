from six import string_types, text_type, PY2
import sys
import copy
import datetime
import re
import time
if __name__ == "__main__":
    cron_type = 'cron_daily'
    arguments = copy.deepcopy(sys.argv)
    remaining_arguments = list()
    while len(arguments):
        if arguments[0] == '-type' and len(arguments) > 1:
            arguments.pop(0)
            cron_type = arguments.pop(0)
            continue
        remaining_arguments.append(arguments.pop(0))
    import docassemble.base.config
    docassemble.base.config.load(arguments=remaining_arguments)
from docassemble.webapp.server import UserModel, UserDict, logmessage, unpack_dictionary, db, set_request_active, fetch_user_dict, save_user_dict, fresh_dictionary, reset_user_dict, obtain_lock_patiently, release_lock, app, login_user, get_user_object, error_notification
import docassemble.webapp.backend
import docassemble.base.interview_cache
import docassemble.base.parse
import docassemble.base.util
import docassemble.base.functions
if PY2:
    import cPickle as pickle
else:
    import pickle
import codecs
from sqlalchemy import or_, and_

set_request_active(False)

def get_cron_user():
    for user in UserModel.query.options(db.joinedload('roles')).all():
        for role in user.roles:
            if role.name == 'cron':
                return(user)
    sys.exit("Cron user not found")

def clear_old_interviews():
    #sys.stderr.write("clear_old_interviews: starting\n")
    interview_delete_days = docassemble.base.config.daconfig.get('interview delete days', 90)
    if interview_delete_days == 0:
        return
    nowtime = datetime.datetime.utcnow()
    #sys.stderr.write("clear_old_interviews: days is " + str(interview_delete_days) + "\n")
    subq = db.session.query(UserDict.key, UserDict.filename, db.func.max(UserDict.indexno).label('indexno')).group_by(UserDict.filename, UserDict.key).subquery()
    last_index = -1
    while True:
        results = db.session.query(UserDict.indexno, UserDict.key, UserDict.filename, UserDict.modtime).join(subq, and_(subq.c.indexno == UserDict.indexno, subq.c.key == UserDict.key, subq.c.filename == UserDict.filename, subq.c.indexno > last_index)).order_by(UserDict.indexno).limit(1000)
        if results.count() == 0:
            break
        stale = list()
        for record in results:
            last_index = record.indexno
            delta = nowtime - record.modtime
            #sys.stderr.write("clear_old_interviews: delta days is " + str(delta.days) + "\n")
            if delta.days > interview_delete_days:
                stale.append(dict(key=record.key, filename=record.filename))
        for item in stale:
            obtain_lock_patiently(item['key'], item['filename'])
            reset_user_dict(item['key'], item['filename'], force=True)
            release_lock(item['key'], item['filename'])
        time.sleep(0.2)
    
def run_cron(cron_type):
    cron_types = [cron_type]
    if not re.search(r'_background$', cron_type):
        cron_types.append(str(cron_type) + "_background")
    cron_user = get_cron_user()
    user_info = dict(is_anonymous=False, is_authenticated=True, email=cron_user.email, theid=cron_user.id, the_user_id=cron_user.id, roles=[role.name for role in cron_user.roles], firstname=cron_user.first_name, lastname=cron_user.last_name, nickname=cron_user.nickname, country=cron_user.country, subdivisionfirst=cron_user.subdivisionfirst, subdivisionsecond=cron_user.subdivisionsecond, subdivisionthird=cron_user.subdivisionthird, organization=cron_user.organization, location=None)
    base_url = docassemble.base.config.daconfig.get('url root', 'http://localhost') + docassemble.base.config.daconfig.get('root', '/')
    path_url = base_url + 'interview'
    with app.app_context():
        with app.test_request_context(base_url=base_url, path=path_url):
            login_user(cron_user, remember=False)
            subq = db.session.query(UserDict.key, UserDict.filename, db.func.max(UserDict.indexno).label('indexno'), db.func.count(UserDict.indexno).label('count')).group_by(UserDict.filename, UserDict.key).filter(UserDict.encrypted == False).subquery()
            last_index = -1
            while True:
                records = [(record.indexno, record.key, record.filename, record.dictionary, record.count) for record in db.session.query(UserDict.key, UserDict.filename, UserDict.dictionary, subq.c.indexno).join(subq, and_(subq.c.indexno == UserDict.indexno, subq.c.key == UserDict.key, subq.c.filename == UserDict.filename, subq.c.indexno > last_index)).order_by(UserDict.indexno).limit(100)]
                if len(records) == 0:
                    break
                to_do = list()
                for indexno, key, filename, dictionary, steps in records:
                    last_index = indexno
                    #dict_result = db.session.query(UserDict.dictionary).filter(UserDict.indexno == indexno).first()
                    try:
                        the_dict = unpack_dictionary(dictionary)
                    except:
                        continue
                    if not the_dict.get('allow_cron', False):
                        continue
                    try:
                        interview = docassemble.base.interview_cache.get_interview(filename)
                    except:
                        continue
                    for cron_type_to_use in cron_types:
                        if cron_type_to_use not in interview.questions:
                            continue
                        if re.search(r'_background$', cron_type_to_use):
                            new_task = docassemble.webapp.worker.background_action.delay(filename, user_info, key, None, None, None, {'action': cron_type_to_use, 'arguments': dict()})
                        else:
                            try:
                                docassemble.base.functions.reset_local_variables()
                                obtain_lock_patiently(key, filename)
                                interview_status = docassemble.base.parse.InterviewStatus(current_info=dict(user=dict(is_anonymous=False, is_authenticated=True, email=cron_user.email, theid=cron_user.id, the_user_id=cron_user.id, roles=[role.name for role in cron_user.roles], firstname=cron_user.first_name, lastname=cron_user.last_name, nickname=cron_user.nickname, country=cron_user.country, subdivisionfirst=cron_user.subdivisionfirst, subdivisionsecond=cron_user.subdivisionsecond, subdivisionthird=cron_user.subdivisionthird, organization=cron_user.organization, location=None, session_uid='cron'), session=key, secret=None, yaml_filename=filename, url=None, url_root=None, encrypted=False, action=cron_type_to_use, interface='cron', arguments=dict()))
                                interview.assemble(the_dict, interview_status)
                                save_status = docassemble.base.functions.this_thread.misc.get('save_status', 'new')
                                if interview_status.question.question_type in ["restart", "exit", "exit_logout"]:
                                    reset_user_dict(key, filename, force=True)
                                if interview_status.question.question_type in ["restart", "exit", "logout", "exit_logout", "new_session"]:
                                    release_lock(key, filename)
                                elif interview_status.question.question_type == "backgroundresponseaction":
                                    new_action = interview_status.question.action
                                    interview_status = docassemble.base.parse.InterviewStatus(current_info=dict(user=user_info, session=key, secret=None, yaml_filename=filename, url=None, url_root=None, encrypted=False, action=new_action['action'], arguments=new_action['arguments'], interface='cron'))
                                    try:
                                        interview.assemble(the_dict, interview_status)
                                    except:
                                        pass
                                    save_status = docassemble.base.functions.this_thread.misc.get('save_status', 'new')
                                    if save_status != 'ignore':
                                        save_user_dict(key, the_dict, filename, encrypt=False, manual_user_id=cron_user.id, steps=steps)
                                    release_lock(key, filename)
                                elif interview_status.question.question_type == "response" and interview_status.questionText == 'null':
                                    release_lock(key, filename)
                                else:
                                    if save_status != 'ignore':
                                        save_user_dict(key, the_dict, filename, encrypt=False, manual_user_id=cron_user.id, steps=steps)
                                    release_lock(key, filename)
                                    if interview_status.question.question_type == "response":
                                        if hasattr(interview_status.question, 'all_variables'):
                                            if hasattr(interview_status.question, 'include_internal'):
                                                include_internal = interview_status.question.include_internal
                                            else:
                                                include_internal = False
                                            sys.stdout.write(docassemble.webapp.backend.dict_as_json(the_dict, include_internal=include_internal).encode('utf8') + "\n")
                                        elif not hasattr(interview_status.question, 'binaryresponse'):
                                            if interview_status.questionText != 'Empty Response':
                                                sys.stdout.write(interview_status.questionText.rstrip().encode('utf8') + "\n")
                            except Exception as err:
                                sys.stderr.write("Cron error: " + text_type(key) + " " + text_type(filename) + " " + text_type(err.__class__.__name__) + ": " + text_type(err) + "\n")
                                release_lock(key, filename)
                                if hasattr(err, 'traceback'):
                                    error_trace = text_type(err.traceback)
                                    if hasattr(err, 'da_line_with_error'):
                                        error_trace += "\nIn line: " + text_type(err.da_line_with_error)
                                else:
                                    error_trace = None
                                error_notification(err, trace=error_trace)
                                continue
                    del the_dict
                    #del dict_result
                time.sleep(0.2)
            
if __name__ == "__main__":
    with app.app_context():
        if cron_type == 'cron_daily':
            clear_old_interviews()
        run_cron(cron_type)
        db.engine.dispose()
    sys.exit(0)

