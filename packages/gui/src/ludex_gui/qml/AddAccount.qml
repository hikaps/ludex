import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

// Add a store account: name and the plugin's own fields; the games are imported once it is saved.
Dialog {
    id: dialog
    objectName: "addAccount"
    property string source: ""
    property var form: ({ fields: [], help: "", name: "" })
    property var values: ({})
    property var pathTarget: null

    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.min(560, Overlay.overlay ? Overlay.overlay.width - 48 : 560)
    padding: 20
    background: Rectangle { radius: Theme.radius; color: Theme.surface2; border.width: 1; border.color: Theme.border }
    header: Txt { text: "Add " + dialog.source + " account"; font.bold: true; font.pixelSize: 18; padding: 20; bottomPadding: 0 }

    function openFor(name) {
        source = name
        form = backend.settingsController.accountForm(name)
        values = {}
        for (var i = 0; i < form.fields.length; i++) {
            if (form.fields[i].kind === "yes_no") {
                values[form.fields[i].name] = "no"
            }
        }
        accountName.text = form.name
        open()
    }

    FolderDialog {
        id: folders
        title: "Choose a folder"
        onAccepted: if (dialog.pathTarget) {
            dialog.pathTarget.text = backend.localPath(selectedFolder.toString())
            dialog.pathTarget.textEdited()
        }
    }

    component Field: TextField {
        Layout.fillWidth: true
        implicitHeight: 36
        color: Theme.text
        placeholderTextColor: Theme.muted
        font.family: Theme.family
        selectByMouse: true
        background: Rectangle { radius: 6; color: Theme.surface; border.width: parent.activeFocus ? 2 : 1; border.color: parent.activeFocus ? Theme.accent : Theme.border }
    }

    contentItem: ColumnLayout {
        spacing: 8
        Txt { Layout.fillWidth: true; text: dialog.form.help || ""; color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap }
        Txt { text: "Account name"; color: Theme.muted; font.pixelSize: Theme.small; Layout.topMargin: 6 }
        Field { id: accountName }
        Repeater {
            model: dialog.form.fields
            delegate: ColumnLayout {
                id: row
                required property var modelData
                Layout.fillWidth: true
                spacing: 4
                Txt { text: row.modelData.label + (row.modelData.help ? "  -  " + row.modelData.help : ""); color: Theme.muted; font.pixelSize: Theme.small; Layout.topMargin: 6; Layout.fillWidth: true; wrapMode: Text.Wrap }
                Toggle {
                    visible: row.modelData.kind === "yes_no"
                    padding: 0
                    onToggled: dialog.values[row.modelData.name] = checked ? "yes" : "no"
                }
                Combo {
                    visible: row.modelData.kind === "choice"
                    Layout.fillWidth: true
                    model: row.modelData.optional ? [""].concat(row.modelData.choices) : row.modelData.choices
                    Component.onCompleted: if (row.modelData.kind === "choice") dialog.values[row.modelData.name] = currentText
                    onActivated: dialog.values[row.modelData.name] = currentText
                }
                RowLayout {
                    visible: row.modelData.kind !== "yes_no" && row.modelData.kind !== "choice"
                    Layout.fillWidth: true
                    Field {
                        id: input
                        echoMode: row.modelData.kind === "secret" ? TextInput.Password : TextInput.Normal
                        onTextEdited: dialog.values[row.modelData.name] = text
                    }
                    Btn { visible: row.modelData.kind === "path"; text: "Browse…"; onClicked: { dialog.pathTarget = input; folders.open() } }
                }
            }
        }
    }

    footer: RowLayout {
        spacing: 8
        Item { Layout.fillWidth: true }
        Btn { text: "Cancel"; onClicked: dialog.close() }
        Btn {
            primary: true
            text: "Add and import"
            onClicked: if (backend.settingsController.addAccount(dialog.source, accountName.text, dialog.values)) dialog.close()
        }
        Item { Layout.preferredWidth: 12 }
    }
}
