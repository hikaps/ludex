import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A keyboard for the controller: A on a text field opens it and what is typed goes into that field.
Popup {
    id: osk
    objectName: "keyboard"
    property Item target: null
    property bool shift: false
    property bool symbols: false
    readonly property var letters: ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
    readonly property var marks: ["!@#$%^&*()", "-_=+[]{}", "/\\:;'\"|", ",.<>?~`"]
    readonly property var rows: symbols ? marks : letters
    readonly property bool multiline: target !== null && target.lineCount !== undefined
    readonly property bool hidden: target !== null && target.echoMode === TextInput.Password

    parent: Overlay.overlay
    modal: true
    z: 100
    focus: true
    padding: 16
    width: Math.min(parent.width - 40, 860)
    x: (parent.width - width) / 2
    y: parent.height - height - 20
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    background: Rectangle { radius: Theme.radius; color: Theme.surface; border.width: 1; border.color: Theme.border }

    function openFor(item) {
        target = item
        shift = false
        symbols = false
        open()
    }
    // Cursor positions count UTF-16 units: step over a surrogate pair as one character.
    function step(from, dir) {
        var at = from + dir
        var unit = target.text.charCodeAt(dir < 0 ? at : from)
        var inside = dir < 0 ? (unit >= 0xDC00 && unit <= 0xDFFF) : (unit >= 0xD800 && unit <= 0xDBFF)
        return Math.max(0, Math.min(target.length, inside ? at + dir : at))
    }
    // Typing or deleting replaces a selection, as in an ordinary text field.
    function dropSelection() {
        var from = target.selectionStart
        var to = target.selectionEnd
        if (from === to) return false
        target.remove(from, to)
        return true
    }
    function type(ch) {
        dropSelection()
        target.insert(target.cursorPosition, ch)
        shift = false
    }
    function backspace() {
        if (dropSelection()) return
        var at = target.cursorPosition
        if (at > 0) target.remove(osk.step(at, -1), at)
    }
    function done() {
        var field = target
        close()
        if (typeof field.accepted === "function") field.accepted()
    }
    onOpened: space.forceActiveFocus(Qt.TabFocusReason)
    onClosed: if (target) target.forceActiveFocus()

    contentItem: ColumnLayout {
        spacing: 8
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 40
            radius: Theme.radius
            color: Theme.bg
            Txt {
                objectName: "keyboardPreview"
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                verticalAlignment: Text.AlignVCenter
                elide: Text.ElideLeft
                text: !osk.target ? "" : osk.hidden ? "•".repeat(osk.target.text.length) : osk.target.text
                color: text.length > 0 ? Theme.text : Theme.muted
            }
        }
        Repeater {
            model: osk.rows
            RowLayout {
                id: line
                required property string modelData
                Layout.alignment: Qt.AlignHCenter
                spacing: 6
                Repeater {
                    model: line.modelData.split("")
                    Btn {
                        required property string modelData
                        objectName: "key-" + modelData
                        Layout.preferredWidth: 64
                        text: osk.shift && !osk.symbols ? modelData.toUpperCase() : modelData
                        onClicked: osk.type(text)
                    }
                }
            }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 6
            Btn { objectName: "shift"; text: "Shift"; primary: osk.shift; visible: !osk.symbols; onClicked: osk.shift = !osk.shift }
            Btn { objectName: "symbols"; text: osk.symbols ? "abc" : "123"; onClicked: { osk.symbols = !osk.symbols; osk.shift = false } }
            Btn { objectName: "left"; text: "Left"; onClicked: osk.target.cursorPosition = osk.step(osk.target.cursorPosition, -1) }
            Btn { id: space; objectName: "space"; Layout.fillWidth: true; text: "Space"; onClicked: osk.type(" ") }
            Btn { objectName: "right"; text: "Right"; onClicked: osk.target.cursorPosition = osk.step(osk.target.cursorPosition, 1) }
            Btn { objectName: "newline"; text: "Enter"; visible: osk.multiline; onClicked: osk.type("\n") }
            Btn { objectName: "delete"; text: "Delete"; onClicked: osk.backspace() }
            Btn { objectName: "clear"; text: "Clear"; onClicked: osk.target.remove(0, osk.target.length) }
            Btn { objectName: "done"; text: "Done"; primary: true; onClicked: osk.done() }
        }
    }
}
