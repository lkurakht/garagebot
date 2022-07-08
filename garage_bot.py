import os
import json
import subprocess
import datetime
import aiohttp
import re
import csv
import prettytable as pt

from typing import Optional

from aiogram import Bot, types
from aiogram.dispatcher import Dispatcher
from aiogram.utils import executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

from bs4 import BeautifulSoup
from bs4 import element

from zap_bd import ZapBaseHandler

bot = Bot(token=os.environ['BOT_TOKEN'])
dp = Dispatcher(bot)
bd = ZapBaseHandler()

botstate: dict[str, str] = {}
lasturl: dict[str, str] = {}


def code_to_url(code: str) -> str:
    return "https://www.exist.ru/Price/?pcode=" + code


def make_keyboard() -> ReplyKeyboardMarkup:
    spares_btn = KeyboardButton('/sparest')
    spares_csv_btn = KeyboardButton('/sparesf')
    cars_btn = KeyboardButton('/cars')
    help_btn = KeyboardButton('/help')
    return ReplyKeyboardMarkup(resize_keyboard=True).add(spares_btn, spares_csv_btn).add(cars_btn, help_btn)


@dp.message_handler(commands=['start', 'help'])
async def send_welcome(message: types.Message):
    await message.reply(
        "Привет!\nРешил наконец-то навести порядок в гараже?\nДавай помогу.\n"
        "/help - вывести справку\n"
        "/cars - вывести список машин\n"
        "/sparest - вывести список запчастей в табличеном виде\n"
        "/sparesf - вывести список запчастей в виде csv-файла\n"
        "/addcar <наазвание машины> - купил очередную трахому? давай добавим в базу\n"
        "/s <текст запроса> - поиск запчасти в гараже по названию\n"
        "/a <номер запчасти> - добавить запчасть с номером\n"
        "При посылки фотографии бот попробует сам распознать штрих-код запчасти\n",
        reply_markup=make_keyboard())


@dp.message_handler(commands=['status'])
async def status(message: types.Message):
    await message.reply(message.text,
                        reply_markup=make_keyboard())


@dp.message_handler(commands=['cars'])
async def cars(message: types.Message):
    table = pt.PrettyTable(['CarId', 'Name'])
    for car in bd.carlist():
        table.add_row([car[0], car[1]])
    await message.reply(f'<pre>{table}</pre>', parse_mode=types.ParseMode.HTML,
                        reply_markup=make_keyboard())


@dp.message_handler(commands=['s'])
async def search(message: types.Message):
    table = pt.PrettyTable(['PartNumber', 'Description', 'Car'])
    for spare in bd.search(message.text.lstrip('/s ')):
        table.add_row([spare[0], spare[2], spare[4]])
    await message.reply(f'<pre>{table}</pre>', parse_mode=types.ParseMode.HTML,
                        reply_markup=make_keyboard())


@dp.message_handler(commands=['sparest'])
async def sparest(message: types.Message):
    table = pt.PrettyTable(['PartNumber', 'Manufacturer', 'Description', 'Car'])
    for spare in bd.spareslist():
        table.add_row([spare[0], spare[1], spare[2], spare[4]])
    await message.reply(f'<pre>{table}</pre>', parse_mode=types.ParseMode.HTML,
                        reply_markup=make_keyboard())


@dp.message_handler(commands=['sparesf'])
async def sparesf(message: types.Message):
    tmpname = ".tmp" + str(datetime.datetime.now()) + ".csv"
    with open(tmpname, 'w') as out:
        csv_out = csv.writer(out)
        csv_out.writerow(['PartNumber', 'Manufacturer', 'Description', 'Link', 'Car'])
        for spare in bd.spareslist():
            csv_out.writerow(spare)
    with open(tmpname, 'rb') as out:
        await message.reply_document(out,
                                     reply_markup=make_keyboard())


@dp.message_handler(commands=['addcar'])
async def addcar(message: types.Message):
    carname = message.text.lstrip("/addcar ")
    if (len(carname)):
        bd.addcar(carname)
        await message.reply(carname + ' added!',
                            reply_markup=make_keyboard())
    else:
        await message.reply('Please specify valid name',
                            reply_markup=make_keyboard())


@dp.callback_query_handler()
async def process_callback(callback_query: types.CallbackQuery):
    global botstate, lasturl
    if botstate[callback_query.from_user.id] == "SelectCat":
        url = callback_query.data
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                resp = await resp.text()
                botstate[callback_query.from_user.id] = resp
                lasturl[callback_query.from_user.id] = url
                await add_zap_from_resp(resp, callback_query.message)
    elif botstate[callback_query.from_user.id] is not None:
        carid = callback_query.data
        spare = parse_zap_page(botstate[callback_query.from_user.id])
        if spare is not None:
            spare = (*spare, lasturl[callback_query.from_user.id], carid)
            bd.addspare(spare)
            botstate[callback_query.from_user.id] = None
            lasturl[callback_query.from_user.id] = None
            await bot.send_message(callback_query.from_user.id, str(spare) + ' added!',
                                   reply_markup=make_keyboard())
        else:
            await bot.send_message(callback_query.from_user.id, 'Error parsing html. Wrong partnum?',
                                   reply_markup=make_keyboard())


@dp.message_handler(commands=['a'])
async def addzap(message: types.Message):
    global botstate, lasturl
    botstate[message.from_user.id] = None
    lasturl[message.from_user.id] = None
    partnum = message.text.lstrip('/a ')
    resp = await fetch_zap(partnum)
    if 'Выберите каталог' in resp:
        catalogues = parse_selectcat_page(resp)
        inline_kb = InlineKeyboardMarkup()
        buttons = []
        for catalogue in catalogues:
            buttons.append(InlineKeyboardButton(catalogue[0] + ' ' + catalogue[1], callback_data=catalogue[2]))
        for b in range(0, len(buttons) - 1, 2):
            inline_kb.add(buttons[b], buttons[b + 1])
        if len(buttons) % 2:
            inline_kb.add(buttons[len(buttons) - 1])
        botstate[message.from_user.id] = "SelectCat"
        await message.reply('Select catalogue: ', reply_markup=inline_kb)
    else:
        lasturl[message.from_user.id] = code_to_url(partnum)
        await add_zap_from_resp(resp, message)


async def add_zap_from_resp(resp: str, message: types.Message):
    global botstate
    botstate[message.from_user.id] = resp
    cars = bd.carlist()
    inline_kb = InlineKeyboardMarkup()
    buttons = []
    for car in cars:
        buttons.append(InlineKeyboardButton(car[1], callback_data=car[0]))
    buttons.append(InlineKeyboardButton("None", callback_data=0))
    for b in range(0, len(buttons) - 1, 2):
        inline_kb.add(buttons[b], buttons[b + 1])
    if len(buttons) % 2:
        inline_kb.add(buttons[len(buttons) - 1])
    await message.reply('Select car: ', reply_markup=inline_kb)


async def fetch_zap(code: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(code_to_url(code)) as resp:
            return await resp.text()


def parse_selectcat_page(html: str) -> list[tuple[str, str, str]]:
    soup = BeautifulSoup(html, 'html.parser')
    data = soup.findAll('ul', {"class": "catalogs"})
    ret = []
    for cathtml in data[0].contents:
        if isinstance(cathtml, element.Tag):
            rex = re.compile(r'\W+')
            try:
                catmanuf = cathtml.findAll('span')[0].text.translate(str.maketrans("\n\t\r", "   "))
                catmanuf = rex.sub(' ', catmanuf)
                catname = cathtml.findAll('dd')[0].text
                catname = rex.sub(' ', catname)
                link = cathtml.findAll('a', href=True)[0]['href']
                catlink = 'https://www.exist.ru' + link
                ret.append((catmanuf, catname, catlink))
            except Exception:
                continue
    return ret


def parse_zap_page(html: str) -> Optional[tuple[str, str, str]]:
    soup = BeautifulSoup(html, 'html.parser')
    search_pattern = re.compile('var _data = (.*);')
    match = None
    for script in soup.find_all("script", {"src": False}):
        if script:
            match = search_pattern.search(script.string)
            if match is not None:
                break
    if match is None:
        return None
    data = match.string[match.string.find('=') + 1:match.string.find('var _favs') - 2]
    json_data = json.loads(data)[0]
    description = json_data['Description'] if json_data['Description'] is not None else "None"
    return (
        json_data['PartNumber'], json_data['CatalogName'],
        description)


@dp.message_handler(content_types=['photo'])
async def handle_docs_photo(message: types.Message):
    tmpname = ".tmp" + str(datetime.datetime.now()) + ".jpg"
    await message.photo[-1].download(tmpname)
    lines = subprocess.run(["zbarimg", tmpname], capture_output=True).stdout.decode('utf-8')
    try:
        partnum = lines[lines.find(':') + 1:lines.find(' ')]
        message.text = '/a ' + partnum
        await addzap(message)
        return
        resp = await fetch_zap(partnum)
        if 'Выберите каталог' in resp:
            cats = parse_selectcat_page(resp)
            inline_kb = InlineKeyboardMarkup()
            buttons = []
            for c in cats:
                buttons.append(InlineKeyboardButton(c[0] + ' ' + c[1], callback_data=c[2]))
            for b in range(0, len(buttons) - 1, 2):
                inline_kb.add(buttons[b], buttons[b + 1])
            if len(buttons) % 2:
                inline_kb.add(buttons[len(buttons) - 1])
            await message.reply('Select catalogue: ', reply_markup=inline_kb)
        else:
            spare = parse_zap_page(resp)
            bd.addspare(spare)
            await message.reply(str(spare) + ' added!')
    except Exception as e:
        await message.reply('error during recognizing: ' + str(e))


if __name__ == '__main__':
    try:
        with open('zapbot.cfg', 'r', encoding='utf-8') as cfgfile:
            cfg = json.load(cfgfile)
        bd_path = cfg["bd_path"]
        print('loading ', bd_path)
    except Exception as e:
        print("Error opening cfg file: ", str(e))
        print("Creating empty bd")
        bd_path = None
    connected_name = bd.connect(bd_path)
    if connected_name != bd_path:
        new_cfg = {}
        new_cfg["bd_path"] = connected_name
        with open('zapbot.cfg', 'w') as outfile:
            json.dump(new_cfg, outfile)
    executor.start_polling(dp)
