import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

Item {
    id: page
    property var pathTarget: null
    property string pendingSpec: ""
    // Unsaved edits, kept here so that saving one section (or a background refresh) never clears another's.
    property var drafts: ({})
    function draftOf(section, name, fallback) {
        var key = section + "/" + name
        return key in drafts ? drafts[key] : fallback
    }
    function setDraft(section, name, value) {
        drafts[section + "/" + name] = value
    }
    function clearDrafts(section) {
        for (var key in drafts) {
            if (key.indexOf(section + "/") === 0) {
                delete drafts[key]
            }
        }
    }

    FolderDialog {
        id: folderDialog
        title: "Choose a folder"
        onAccepted: if (page.pathTarget) {
            page.pathTarget.text = backend.localPath(selectedFolder.toString())
            page.pathTarget.textEdited()
        }
    }


    AddAccount { id: newAccount }

    Dialog {
        id: forget
        objectName: "forgetAccount"
        property string ref: ""
        modal: true
        anchors.centerIn: Overlay.overlay
        padding: 20
        background: Rectangle { radius: Theme.radius; color: Theme.surface2; border.width: 1; border.color: Theme.border }
        header: Txt { text: "Remove account"; font.bold: true; font.pixelSize: 16; padding: 20; bottomPadding: 0 }
        contentItem: Txt { width: 420; wrapMode: Text.Wrap; lineHeight: 1.2; text: "Remove " + forget.ref + " and its games from the library? Games another account owns stay. Your files and the store are untouched." }
        footer: DialogButtonBox {
            padding: 16
            spacing: 8
            background: Item { }
            delegate: Btn { }
            standardButtons: Dialog.Yes | Dialog.Cancel
        }
        onOpened: standardButton(Dialog.Cancel).forceActiveFocus()
        onAccepted: backend.settingsController.removeAccount(forget.ref)
    }

    Dialog {
        id: trust
        objectName: "trust"
        modal: true
        anchors.centerIn: Overlay.overlay
        padding: 20
        background: Rectangle { radius: Theme.radius; color: Theme.surface2; border.width: 1; border.color: Theme.border }
        header: Txt { text: "Add plugin"; font.bold: true; font.pixelSize: 16; padding: 20; bottomPadding: 0 }
        contentItem: Txt {
            width: 420
            wrapMode: Text.Wrap
            lineHeight: 1.2
            text: "A plugin runs with your permissions. Install only code you trust.\n\nAdd " + page.pendingSpec + "?"
        }
        footer: DialogButtonBox {
            padding: 16
            spacing: 8
            background: Item { }
            delegate: Btn { }
            standardButtons: Dialog.Yes | Dialog.Cancel
        }
        onOpened: standardButton(Dialog.Cancel).forceActiveFocus()
        onAccepted: backend.settingsController.addPlugin(page.pendingSpec)
    }

    Flickable {
        anchors.fill: parent
        contentHeight: column.implicitHeight + 48
        clip: true
        ScrollBar.vertical: ScrollBar {}

        ColumnLayout {
            id: column
            x: 24
            y: 24
            width: parent.width - 48
            spacing: 18

            Txt { text: "Settings"; font.pixelSize: Theme.title; font.bold: true }

            Repeater {
                model: backend.settingsController.sections
                delegate: Rectangle {
                    id: section
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: body.implicitHeight + 32
                    radius: Theme.radius
                    color: Theme.surface
                    border.width: 1
                    border.color: Theme.border

                    function collect() {
                        var out = {}
                        for (var i = 0; i < modelData.fields.length; i++) {
                            var f = modelData.fields[i]
                            out[f.name] = page.draftOf(modelData.id, f.name, f.value)
                        }
                        return out
                    }
                    function edit(name, value) {
                        page.setDraft(modelData.id, name, value)
                    }

                    ColumnLayout {
                        id: body
                        anchors.fill: parent
                        anchors.margins: 16
                        spacing: 10
                        Txt { text: section.modelData.title; font.bold: true; font.pixelSize: 16 }
                        Txt { visible: section.modelData.hint !== ""; Layout.fillWidth: true; text: section.modelData.hint; color: Theme.muted; font.pixelSize: Theme.small; wrapMode: Text.Wrap }

                        Repeater {
                            model: section.modelData.fields
                            delegate: RowLayout {
                                id: row
                                required property var modelData
                                readonly property bool toggle: modelData.kind === "yes_no"
                                Layout.fillWidth: true
                                spacing: 12

                                Txt {
                                    Layout.fillWidth: !(row.toggle === false)
                                    Layout.preferredWidth: row.toggle ? -1 : 200
                                    text: row.modelData.label
                                    wrapMode: Text.Wrap
                                    color: row.toggle ? Theme.text : Theme.muted
                                    ToolTip.visible: hover.hovered && row.modelData.help !== ""
                                    ToolTip.text: row.modelData.help
                                    HoverHandler { id: hover }
                                }
                                Toggle {
                                    id: toggle
                                    padding: 0
                                    visible: row.toggle
                                    checked: (section.modelData.instant ? row.modelData.value : page.draftOf(section.modelData.id, row.modelData.name, row.modelData.value)) === "yes"
                                    onToggled: {
                                        var value = checked ? "yes" : "no"
                                        if (section.modelData.instant) {
                                            backend.settingsController.setInstant(section.modelData.id, row.modelData.name, value)
                                        } else {
                                            section.edit(row.modelData.name, value)
                                        }
                                    }
                                }
                                Combo {
                                    visible: row.modelData.kind === "choice"
                                    Layout.fillWidth: true
                                    model: row.modelData.optional ? [""].concat(row.modelData.choices) : row.modelData.choices
                                    currentIndex: Math.max(0, model.indexOf(page.draftOf(section.modelData.id, row.modelData.name, row.modelData.value)))
                                    onActivated: section.edit(row.modelData.name, currentText)
                                }
                                TextField {
                                    id: input
                                    visible: !row.toggle && row.modelData.kind !== "choice"
                                    Layout.fillWidth: true
                                    text: page.draftOf(section.modelData.id, row.modelData.name, row.modelData.value)
                                    echoMode: row.modelData.kind === "secret" ? TextInput.Password : TextInput.Normal
                                    placeholderText: row.modelData.kind === "secret" && row.modelData.hasValue ? "(set; type to replace)" : ""
                                    placeholderTextColor: Theme.muted
                                    color: Theme.text
                                    font.family: Theme.family
                                    selectByMouse: true
                                    background: Rectangle { radius: 6; color: Theme.surface2; border.width: input.activeFocus ? 2 : 1; border.color: input.activeFocus ? Theme.accent : Theme.border }
                                    onTextEdited: section.edit(row.modelData.name, text)
                                }
                                Btn {
                                    visible: row.modelData.kind === "path"
                                    text: "Browse…"
                                    onClicked: { page.pathTarget = input; folderDialog.open() }
                                }
                            }
                        }
                        RowLayout {
                            visible: section.modelData.id === "plugins"
                            Layout.fillWidth: true
                            spacing: 10
                            TextField {
                                id: spec
                                Layout.fillWidth: true
                                placeholderText: "Git link, package name or folder of a plugin"
                                placeholderTextColor: Theme.muted
                                color: Theme.text
                                font.family: Theme.family
                                selectByMouse: true
                                implicitHeight: 36
                                background: Rectangle { radius: 6; color: Theme.surface2; border.width: spec.activeFocus ? 2 : 1; border.color: spec.activeFocus ? Theme.accent : Theme.border }
                                onAccepted: addButton.clicked()
                            }
                            Btn {
                                id: addButton
                                primary: true
                                text: backend.settingsController.installing ? "Adding…" : "Add plugin"
                                enabled: !backend.settingsController.installing && spec.text.trim() !== ""
                                onClicked: if (enabled) { page.pendingSpec = spec.text.trim(); trust.open() }
                            }
                        }
                        RowLayout {
                            visible: section.modelData.id === "accounts" && section.modelData.sources.length > 0
                            Layout.fillWidth: true
                            spacing: 10
                            Combo { id: sourcePick; Layout.fillWidth: true; model: section.modelData.sources }
                            Btn { primary: true; text: "Add account"; onClicked: newAccount.openFor(sourcePick.currentText) }
                        }
                        Btn {
                            visible: section.modelData.id.indexOf("account:") === 0
                            text: "Remove account"
                            Layout.alignment: Qt.AlignRight
                            onClicked: { forget.ref = section.modelData.id.substring(8); forget.open() }
                        }
                        Btn {
                            visible: !section.modelData.instant
                            primary: true
                            text: "Save"
                            Layout.alignment: Qt.AlignRight
                            onClicked: {
                                const values = section.collect()
                                page.clearDrafts(section.modelData.id)
                                backend.settingsController.save(section.modelData.id, values)
                            }
                        }
                    }
                }
            }
        }
    }
}
