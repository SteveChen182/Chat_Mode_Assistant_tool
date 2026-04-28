# Chatter - Chat with Webpages

A Chrome extension that allows you to have natural language conversations about any webpage using Azure OpenAI.

## Features

- 💬 **Natural Language Q&A**: Ask questions about webpage content in natural language
- 📋 **Clipboard Support**: Load and chat with clipboard content (text, code, documents)
- 🌐 **Multi-language Support**: Interface and responses in Traditional Chinese, Simplified Chinese, and English
- 🔄 **Conversation Context**: Maintains chat history for follow-up questions
- 📄 **Side Panel Interface**: Clean, distraction-free side panel UI
- ⚡ **Azure OpenAI Powered**: Uses GPT-4o for intelligent responses

## How to Use

1. **Load Content**
   
   **Option A: Load Page Content**
   - Click the extension icon to open the side panel
   - Click "Load Page" button to load the current webpage content
   - The page title and URL will be displayed
   - ⚠️ **Important**: Loading new content will automatically clear previous conversation history
   
   **Option B: Load Clipboard Content**
   - Copy any text to your clipboard (e.g., from a document, email, or code editor)
   - Click the extension icon to open the side panel
   - Click "Load Clipboard" button to load the clipboard content
   - Perfect for: analyzing code, reviewing documents, translating text, etc.

2. **Ask Questions**
   - Type your question in the input box
   - Press Enter or click "Send" to submit
   - The AI will respond based on the page content

3. **Continue Conversation**
   - Ask follow-up questions about the same page
   - The AI remembers the conversation context
   - All previous messages are visible in the chat

4. **Switch to Different Page**
   - Navigate to a new webpage in the browser
   - Click "Load Page" again to load the new page content
   - Previous conversation will be automatically cleared
   - Start asking questions about the new page

5. **Clear Chat**
   - Click "Clear Chat" to start a fresh conversation
   - This will clear all messages but keep the current page loaded

6. **Change Language**
   - Click the language buttons (繁/簡/EN) in the top-right corner
   - Both the UI and AI responses will switch to the selected language

## Technical Details

### Azure OpenAI Configuration
- **Endpoint**: Intel's Azure OpenAI instance
- **Deployment**: GPT-4o-Global-POCs-Saha
- **API Version**: 2023-05-15

### Permissions
- `activeTab`: Access current tab content
- `scripting`: Extract webpage text
- `storage`: Save language preferences
- `sidePanel`: Display side panel interface

### Architecture
- **Manifest V3**: Latest Chrome extension format
- **Service Worker**: Background script for API calls
- **Side Panel**: Modern Chrome side panel API

## Development

### File Structure
```
chatter/
├── manifest.json         # Extension configuration
├── background.js         # Service worker (API calls)
├── sidepanel.html        # Side panel UI
├── sidepanel.js          # Side panel logic
├── options.html          # Options page
└── README.md            # This file
```

### Key Components

**background.js**
- Handles Azure OpenAI API calls
- Extracts webpage content
- Manages chat messages

**sidepanel.js**
- Chat UI logic
- Message display
- Language switching
- User input handling

## Notes

- Page content is truncated to 15,000 characters to fit within API limits
- **Conversation history is automatically cleared when loading a new page** to prevent confusion between different pages
- Conversation history is also cleared when side panel closes
- Language preference is saved locally and persists across sessions

## Version

**1.0.1** - Fixed: Conversation history now clears automatically when loading new pages

**1.0.0** - Initial release with core chat functionality and multi-language support
