import re
from time import gmtime, strftime

from bson.objectid import ObjectId

from telethon.tl.functions.users import GetFullUserRequest
from telethon import custom, errors
from telethon.tl.custom import Button

from aiogram import types

from sophie_bot import tbot, decorator, mongodb, logger, dp
from sophie_bot.modules.connections import connection, get_conn_chat
from sophie_bot.modules.disable import disablable_dec
from sophie_bot.modules.helper_func.flood import flood_limit_dec
from sophie_bot.modules.language import get_string, get_strings_dec
from sophie_bot.modules.users import (check_group_admin, is_user_admin,
                                      user_admin_dec, user_link, add_user_to_db)
from sophie_bot.modules.helper_func.notes import save_get_new_note


@decorator.command('owo')
@user_admin_dec
@connection()
@get_strings_dec("notes")
async def test(message, strings, status, chat_id, chat_title):
    print(message)


@decorator.t_command("save", word_arg=True)
@user_admin_dec
@connection(admin=True)
@get_strings_dec("notes")
async def save_note(event, strings, status, chat_id, chat_title):
    note_name, file_id, note_text = await save_get_new_note(event, strings, chat_id)

    status = strings["saved"]
    old = mongodb.notes.find_one({'chat_id': chat_id, "name": note_name})
    date = strftime("%Y-%m-%d %H:%M:%S", gmtime())
    created_date = date
    creator = None
    if old:
        if 'created' in old:
            created_date = old['created']
        if 'creator' in old:
            creator = old['creator']
        status = strings["updated"]

    if not creator:
        creator = event.from_id

    new = ({'chat_id': chat_id,
            'name': note_name,
            'text': note_text,
            'date': date,
            'created': created_date,
            'updated_by': event.from_id,
            'creator': creator,
            'file_id': file_id})

    buttons = None

    if old:
        mongodb.notes.update_one({'_id': old['_id']}, {"$set": new}, upsert=False)
        new = None
    else:
        new = mongodb.notes.insert_one(new).inserted_id

        buttons = [
            [Button.inline(strings["del_note"], 'delnote_{}'.format(new))]
        ]

    text = strings["note_saved_or_updated"].format(
        note_name=note_name, status=status, chat_title=chat_title)
    text += strings["you_can_get_note"].format(name=note_name)

    await event.reply(text, buttons=buttons)


@decorator.t_command("clear", arg=True)
@user_admin_dec
@connection(admin=True)
@get_strings_dec("notes")
async def clear_note(event, strings, status, chat_id, chat_title):
    note_name = event.pattern_match.group(1)
    note = mongodb.notes.delete_one({'chat_id': chat_id, "name": note_name})
    if note:
        text = strings["note_removed"].format(
            note_name=note_name, chat_name=chat_title)
    else:
        text = strings["cant_find_note"].format(chat_name=chat_title)
    await event.reply(text)


@decorator.t_command("noteinfo", arg=True)
@user_admin_dec
@connection(admin=True)
@get_strings_dec("notes")
async def noteinfo(event, strings, status, chat_id, chat_title):
    note_name = event.pattern_match.group(1)
    note = mongodb.notes.find_one({'chat_id': chat_id, "name": note_name})
    if not note:
        text = strings["cant_find_note"]
    else:
        text = strings["note_info_title"]
        text += strings["note_info_note"].format(note_name=note_name)
        text += strings["note_info_created"].format(
            data=note['created'], user=await user_link(note['creator']))
        text += strings["note_info_updated"].format(
            data=note['date'], user=await user_link(note['updated_by']))

    await event.reply(text)


@decorator.t_command("notes ?(.*)")
@flood_limit_dec("notes")
@disablable_dec("notes")
@connection()
@get_strings_dec("notes")
async def list_notes(event, strings, status, chat_id, chat_title):
    notes = mongodb.notes.find({'chat_id': chat_id}).sort("name", 1)
    text = strings["notelist_header"].format(chat_name=chat_title)
    if notes.count() == 0:
        text = strings["notelist_no_notes"]
    else:
        for note in notes:
            text += "- `#{}`\n".format(note['name'])
    await event.reply(text)


async def send_note(chat_id, group_id, msg_id, note_name,
                    show_none=False, noformat=False, preview=False,
                    from_id=""):
    file_id = None
    note = mongodb.notes.find_one({'chat_id': int(group_id), 'name': note_name})
    if not note and show_none is True:
        await tbot.send_message(chat_id, get_string(
            "notes", "note_not_found", chat_id), reply_to=msg_id)
        return
    elif not note:
        return None

    if note['file_id']:
        file_id = note['file_id']

    if not file_id:
        file_id = None

    if noformat is True:
        format = None
        string = note['text']
        buttons = ""
    else:
        string, buttons = button_parser(group_id, note['text'])
        h = re.search(r"(\[format:(markdown|md|html|none)\])", string)
        if h:
            string = string.replace(h.group(1), "")
            format_raw = h.group(2).lower()
            if format_raw == 'markdown' or format_raw == 'md':
                format = 'md'
            elif format_raw == 'html':
                format = 'html'
            elif format_raw == 'none':
                format = None
        else:
            format = 'md'

        r = re.search(r"(\[preview:(yes|no)\])", string)
        if r:
            string = string.replace(r.group(1), "")
            preview_raw = r.group(2).lower()
            if preview_raw == "yes":
                preview = True
            elif preview_raw == "no":
                preview = False

    if len(string.rstrip()) == 0:
        if noformat is True:
            string = "Note {}\n\n".format(note_name)
        else:
            string = "**Note {}**\n\n".format(note_name)

    if not buttons:
        buttons = None

    if from_id:
        user = mongodb.user_list.find_one({"user_id": from_id})
        if not user:
            user = await add_user_to_db(await tbot(GetFullUserRequest(int(from_id))))
        if 'last_name' in user:
            last_name = user['last_name']
            if not last_name:
                last_name = ""
            full_name = user['first_name'] + " " + last_name
        else:
            last_name = None
            full_name = user['first_name']

        if 'username' in user:
            username = "@" + user['username']
        else:
            username = None

        chatname = mongodb.chat_list.find_one({'chat_id': group_id})

        # Format vars
        string = string.format(
            first=user['first_name'],
            last=last_name,
            fullname=full_name,
            username=username,
            mention=await user_link(from_id),
            id=from_id,
            chatname=chatname['chat_title'],
            rules='Will be later'
        )

    try:
        return await tbot.send_message(
            chat_id,
            string,
            buttons=buttons,
            parse_mode=format,
            reply_to=msg_id,
            file=file_id,
            link_preview=preview
        )
    except Exception as err:
        await tbot.send_message(chat_id, str(err))
        logger.error("Error in send_note/send_message: " + str(err))


@decorator.CallBackQuery(b'delnote_', compile=True)
@flood_limit_dec("delnote_handler")
async def del_note_callback(event):
    user_id = event.query.user_id
    if await is_user_admin(event.chat_id, user_id) is False:
        return
    note_id = re.search(r'delnote_(.*)', str(event.data)).group(1)[:-1]
    note = mongodb.notes.find_one({'_id': ObjectId(note_id)})
    if note:
        mongodb.notes.delete_one({'_id': note['_id']})

    link = await user_link(user_id)
    await event.edit(get_string("notes", "note_deleted_by", event.chat_id).format(
        note_name=note['name'], user=link), link_preview=False)


@dp.message_handler(commands=['get'], commands_prefix='!/#')
async def get_note(message):
    status, chat_id, chat_title = await get_conn_chat(message['from']['id'], message['chat']['id'])
    args = message['text'].split(" ", 3)
    if not args:
        return

    note_name = args[1].lower()
    if note_name[0] == "#":
        note_name = note_name[1:]
    if len(args) >= 3 and args[2].lower() == "noformat":
        noformat = True
    else:
        noformat = False
    if len(note_name) >= 1:
        await send_note(
            message['chat']['id'], chat_id, message['message_id'], note_name,
            show_none=True, noformat=noformat, from_id=message['from']['id'])


@decorator.StrictCommand("^#(.*)")
@connection()
async def check_hashtag(event, status, chat_id, chat_title):
    status, chat_id, chat_title = await get_conn_chat(event.from_id, event.chat_id)
    if event.message.reply_to_msg_id:
        msg = event.message.reply_to_msg_id
    else:
        msg = event.message.id
    if status is False:
        await message.reply(chat_id)
        return
    note_name = message['text'][1:].split(" ", 2)[0].lower()
    print(note_name)
    if len(note_name) >= 1:
        await send_note(
            event.chat_id, chat_id, msg, note_name,
            from_id=event.from_id)


def button_parser(chat_id, texts):
    buttons = []
    raw_buttons = re.findall(r'\[(.+?)\]\(button(.+?):(.+?)(:same|)\)', texts)
    text = re.sub(r'\[(.+?)\]\(button(.+?):(.+?)(:same|)\)', '', texts)
    for raw_button in raw_buttons:
        if raw_button[1] == 'url':
            url = raw_button[2]
            if url[0] == '/' and url[0] == '/':
                url = url[2:]
            t = [custom.Button.url(raw_button[0], url)]
        elif raw_button[1] == 'note':
            t = [Button.inline(raw_button[0], 'get_note_{}_{}'.format(
                chat_id, raw_button[2]))]
        elif raw_button[1] == 'alert':
            t = [Button.inline(raw_button[0], 'get_alert_{}_{}'.format(
                chat_id, raw_button[2]))]
        elif raw_button[1] == 'deletemsg':
            t = [Button.inline(raw_button[0], 'get_delete_msg_{}_{}'.format(
                chat_id, raw_button[2]))]

        if raw_button[3]:
            new = buttons[-1] + t
            buttons = buttons[:-1]
            buttons.append(new)
        else:
            buttons.append(t)

    return text, buttons


@decorator.CallBackQuery(b'get_note_')
async def get_note_callback(event):
    data = str(event.data)
    event_data = re.search(r'get_note_(.*)_(.*)', data)
    notename = event_data.group(2)[:-1]
    group_id = event_data.group(1)
    user_id = event.original_update.user_id
    try:
        await send_note(user_id, group_id, None, notename)
        await event.answer(get_string("notes", "pmed_note", event.chat_id))
    except errors.rpcerrorlist.UserIsBlockedError or errors.rpcerrorlist.PeerIdInvalidError:
        await event.answer(
            get_string("notes", "user_blocked", event.chat_id), alert=True)


@decorator.CallBackQuery(b'get_alert_')
async def get_alert_callback(event):
    data = str(event.data)
    event_data = re.search(r'get_alert_(.*)_(.*)', data)
    notename = event_data.group(2)[:-1]
    group_id = event_data.group(1)
    note = mongodb.notes.find_one({'chat_id': int(group_id), 'name': notename})
    if not note:
        await event.answer(get_string("notes", "cant_find_note", event.chat_id), alert=True)
        return
    text = note['text']
    if len(text) >= 200:
        await event.answer(
            get_string("notes", "note_so_big", event.chat_id), alert=True)
        return

    await event.answer(text, alert=True)


@decorator.CallBackQuery(b'get_delete_msg_')
async def del_message_callback(event):
    data = str(event.data)
    event_data = re.search(r'get_delete_msg_(.*)_(.*)', data)
    if 'admin' in event_data.group(2):
        user_id = event.query.user_id
        if await check_group_admin(event, user_id, no_msg=True) is False:
            return
    elif 'user' in event_data.group(2):
        pass
    else:
        await event.answer(
            get_string("notes", "delmsg_no_arg", event.chat_id), alert=True)
        return

    await event.delete()
