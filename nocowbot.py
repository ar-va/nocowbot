import apscheduler.util
import pytz


# Patch apscheduler.util.astimezone so that if the timezone isn't a pytz timezone, it returns pytz.utc.
def patched_astimezone(timezone):
    if timezone is None or not hasattr(timezone, 'localize'):
        return pytz.utc
    return timezone


apscheduler.util.astimezone = patched_astimezone

import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    JobQueue,
)
import yt_dlp

# Define conversation states
LINK, CHOICE, QUALITY, AUDIO_FORMAT = range(4)

# Create a folder for downloads if it doesn't exist
if not os.path.exists('downloads'):
    os.makedirs('downloads')

# Set up logging for debugging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Welcome! Please send me a video link (YouTube, Instagram, TikTok, Twitter, etc.)"
    )
    return LINK


async def link_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    if "http" not in text:
        await update.message.reply_text(
            "That doesn't look like a valid link. Please send a proper video link."
        )
        return LINK
    context.user_data['link'] = text
    keyboard = [
        [InlineKeyboardButton("Video", callback_data='video')],
        [InlineKeyboardButton("Audio", callback_data='audio')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Do you want to download Video or Audio?", reply_markup=reply_markup)
    return CHOICE


async def choice_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data
    context.user_data['choice'] = choice
    if choice == 'video':
        keyboard = [
            [InlineKeyboardButton("Low Quality", callback_data='low')],
            [InlineKeyboardButton("Medium Quality", callback_data='medium')],
            [InlineKeyboardButton("High Quality", callback_data='high')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="Select video quality:")
        await query.message.reply_text("Choose video quality:", reply_markup=reply_markup)
        return QUALITY
    elif choice == 'audio':
        keyboard = [
            [InlineKeyboardButton("MP3", callback_data='mp3')],
            [InlineKeyboardButton("M4A", callback_data='m4a')],
            [InlineKeyboardButton("AAC", callback_data='aac')],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text="Select audio format:")
        await query.message.reply_text("Choose audio format:", reply_markup=reply_markup)
        return AUDIO_FORMAT
    else:
        await query.edit_message_text(text="Invalid choice. Please start over.")
        return ConversationHandler.END


async def quality_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    quality = query.data
    context.user_data['quality'] = quality
    await query.edit_message_text(text=f"You selected {quality} quality video. Downloading now...")
    await download_and_send(update, context)
    return ConversationHandler.END


async def audio_format_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    audio_format = query.data
    context.user_data['audio_format'] = audio_format
    await query.edit_message_text(text=f"You selected {audio_format} audio format. Downloading now...")
    await download_and_send(update, context)
    return ConversationHandler.END


async def download_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    link = context.user_data.get('link')
    choice = context.user_data.get('choice')
    outtmpl = 'downloads/%(title)s.%(ext)s'

    # Configure yt-dlp options based on the user's choice
    if choice == 'video':
        quality = context.user_data.get('quality')
        if quality == 'low':
            format_option = 'worstvideo+bestaudio/worst'
        elif quality == 'medium':
            format_option = 'best[height<=480]'
        else:  # high quality
            format_option = 'bestvideo+bestaudio/best'
        ydl_opts = {
            'format': format_option,
            'outtmpl': outtmpl,
            'merge_output_format': 'mp4'
        }
    elif choice == 'audio':
        audio_format = context.user_data.get('audio_format')
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': outtmpl,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': audio_format,
                'preferredquality': '192',
            }],
        }
    else:
        await update.effective_message.reply_text("Invalid option selected.")
        return

    file_path = None
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(link, download=True)
            if choice == 'audio':
                file_path = ydl.prepare_filename(info)
                file_path = os.path.splitext(file_path)[0] + '.' + context.user_data.get('audio_format')
            else:
                file_path = ydl.prepare_filename(info)
    except Exception as e:
        await update.effective_message.reply_text(f"An error occurred: {e}")
        return

    if file_path and os.path.exists(file_path):
        try:
            if choice == 'video':
                await context.bot.send_video(chat_id=chat_id, video=open(file_path, 'rb'))
            else:
                await context.bot.send_audio(chat_id=chat_id, audio=open(file_path, 'rb'))
            await update.effective_message.reply_text("Here is your file!")
        except Exception as e:
            await update.effective_message.reply_text(f"Error sending file: {e}")
    else:
        await update.effective_message.reply_text("Download failed. Please try again.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Operation cancelled.')
    return ConversationHandler.END


def main():
    token = "7927372636:AAF4VodpMWkYeSaucyUPWD3TAffAupToUt4"

    # Create the JobQueue (the patched timezone handling is active above)
    job_queue = JobQueue()

    # Build the Application and pass in the JobQueue
    app = Application.builder().token(token).job_queue(job_queue).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, link_received)],
            CHOICE: [CallbackQueryHandler(choice_received)],
            QUALITY: [CallbackQueryHandler(quality_received)],
            AUDIO_FORMAT: [CallbackQueryHandler(audio_format_received)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    app.add_handler(conv_handler)
    app.run_polling()


if __name__ == '__main__':
    main()
