import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

// A game's launch options: Proton runner, prefix, executable, arguments, environment.
Dialog {
    id: dialog
    objectName: "launchOptions"
    property int gameId: -1
    property var info: ({ available: false, reason: "" })

    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.min(640, Overlay.overlay ? Overlay.overlay.width - 48 : 640)
    padding: 20
    background: Rectangle { radius: Theme.radius; color: Theme.surface2; border.width: 1; border.color: Theme.border }
    header: Txt { text: "Launch options"; font.bold: true; font.pixelSize: 18; padding: 20; bottomPadding: 0 }

    function openFor(id) {
        gameId = id
        info = backend.gameSettings(id)
        if (info.available) {
            runner.currentIndex = Math.max(0, runner.model.indexOf(info.runner))
            prefix.text = info.prefix
            executable.text = info.executable
            args.text = info.args
            env.text = info.env
        }
        open()
    }

    FolderDialog {
        id: folders
        title: "Prefix folder"
        onAccepted: prefix.text = backend.localPath(selectedFolder.toString())
    }

    component Field: TextField {
        Layout.fillWidth: true
        color: Theme.text
        placeholderTextColor: Theme.muted
        font.family: Theme.family
        selectByMouse: true
        implicitHeight: 36
        background: Rectangle { radius: 6; color: Theme.surface; border.width: parent.activeFocus ? 2 : 1; border.color: parent.activeFocus ? Theme.accent : Theme.border }
    }

    contentItem: ColumnLayout {
        spacing: 8
        Txt {
            visible: !dialog.info.available
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            color: Theme.muted
            text: dialog.info.reason || ""
        }
        ColumnLayout {
            visible: dialog.info.available === true
            Layout.fillWidth: true
            spacing: 6
            Txt { text: "Runner (Proton build; Native runs the executable directly)"; color: Theme.muted; font.pixelSize: Theme.small }
            Combo {
                id: runner
                Layout.fillWidth: true
                model: ["Native"].concat(dialog.info.runners || [])
            }
            Txt { text: "Prefix folder (blank: " + (dialog.info.defaultPrefix || "") + "/<game>)"; color: Theme.muted; font.pixelSize: Theme.small; Layout.topMargin: 6 }
            RowLayout {
                Layout.fillWidth: true
                Field { id: prefix }
                Btn { text: "Browse…"; onClicked: folders.open() }
            }
            Txt { text: "Executable (relative to the game folder or absolute; blank: automatic)"; color: Theme.muted; font.pixelSize: Theme.small; Layout.topMargin: 6 }
            Field { id: executable }
            Combo {
                visible: (dialog.info.candidates || []).length > 0
                Layout.fillWidth: true
                model: ["Pick one found in the game folder"].concat(dialog.info.candidates || [])
                onActivated: if (currentIndex > 0) { executable.text = currentText; currentIndex = 0 }
            }
            Txt { text: "Arguments"; color: Theme.muted; font.pixelSize: Theme.small; Layout.topMargin: 6 }
            Field { id: args }
            Txt { text: "Environment variables, one NAME=VALUE per line"; color: Theme.muted; font.pixelSize: Theme.small; Layout.topMargin: 6 }
            ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: 100
                TextArea {
                    id: env
                    color: Theme.text
                    font.family: Theme.family
                    selectByMouse: true
                    background: Rectangle { radius: 6; color: Theme.surface; border.width: env.activeFocus ? 2 : 1; border.color: env.activeFocus ? Theme.accent : Theme.border }
                }
            }
        }
    }

    footer: RowLayout {
        spacing: 8
        Item { Layout.fillWidth: true }
        Btn { text: dialog.info.available ? "Cancel" : "Close"; onClicked: dialog.close() }
        Btn {
            visible: dialog.info.available === true
            primary: true
            text: "Save"
            onClicked: {
                backend.saveGameSettings(dialog.gameId, {
                    runner: runner.currentIndex > 0 ? runner.currentText : "",
                    prefix: prefix.text,
                    executable: executable.text,
                    args: args.text,
                    env: env.text
                })
                dialog.close()
            }
        }
        Item { Layout.preferredWidth: 12 }
    }
}
