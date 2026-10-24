from datetime import datetime

from telegram import Chat, Message, User

from app.utils.telegram import is_triggered

BOT = User(id=999, first_name="ClassRepAI", is_bot=True, username="ClassRepAIBot")
STUDENT = User(id=1, first_name="Rafi", is_bot=False)
GROUP = Chat(id=-100, type="supergroup")
PRIVATE = Chat(id=1, type="private")


def msg(chat=GROUP, text=None, caption=None, reply_to=None):
    return Message(message_id=1, date=datetime.now(), chat=chat, from_user=STUDENT,
                   text=text, caption=caption, reply_to_message=reply_to)


def check(m):
    return is_triggered(m, "ClassRepAIBot", 999)


def test_plain_group_message_is_ignored():
    assert not check(msg(text="kal ki class ache?"))


def test_mention_in_text():
    assert check(msg(text="@classrepaibot kal ki class ache?"))


def test_mention_in_caption():
    assert check(msg(caption="routine @ClassRepAIBot"))


def test_similar_username_is_not_a_mention():
    assert not check(msg(text="@ClassRepAIBotFan hi"))


def test_reply_to_bot():
    bot_msg = Message(message_id=0, date=datetime.now(), chat=GROUP, from_user=BOT, text="Saved?")
    assert check(msg(text="yes save it", reply_to=bot_msg))


def test_private_chat_always_triggers():
    assert check(msg(chat=PRIVATE, text="hello"))
