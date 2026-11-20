import QtQuick

// The only text item in the UI: plugin and store text is never rich text or markup.
Text {
    color: Theme.text
    font.family: Theme.family
    font.pixelSize: Theme.body
    textFormat: Text.PlainText
}
