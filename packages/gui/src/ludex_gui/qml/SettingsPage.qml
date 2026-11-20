import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

Item {
    id: page
    property var pathTarget: null

    FolderDialog {
        id: folderDialog
        title: "Choose a folder"
        onAccepted: if (page.pathTarget) page.pathTarget.text = selectedFolder.toString().replace(/^file:\/\//, "")
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
            width: Math.min(parent.width - 48, 860)
            spacing: 18

            Txt { text: "Settings"; font.pixelSize: Theme.title; font.bold: true }

            Repeater {
                model: backend.settingsController.sections
                delegate: Rectangle {
                    id: section
                    required property var modelData
                    property var edits: ({})
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
                            out[f.name] = f.name in edits ? edits[f.name] : f.value
                        }
                        return out
                    }
                    function edit(name, value) {
                        var e = edits
                        e[name] = value
                        edits = e
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

                                Switch {
                                    id: toggle
                                    visible: row.toggle
                                    checked: row.modelData.value === "yes"
                                    onToggled: {
                                        var value = checked ? "yes" : "no"
                                        if (section.modelData.instant) {
                                            backend.settingsController.setInstant(section.modelData.id, row.modelData.name, value)
                                        } else {
                                            section.edit(row.modelData.name, value)
                                        }
                                    }
                                }
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
                                ComboBox {
                                    visible: row.modelData.kind === "choice"
                                    Layout.fillWidth: true
                                    model: row.modelData.optional ? [""].concat(row.modelData.choices) : row.modelData.choices
                                    currentIndex: Math.max(0, model.indexOf(row.modelData.value))
                                    font.family: Theme.family
                                    onActivated: section.edit(row.modelData.name, currentText)
                                }
                                TextField {
                                    id: input
                                    visible: !row.toggle && row.modelData.kind !== "choice"
                                    Layout.fillWidth: true
                                    text: row.modelData.value
                                    echoMode: row.modelData.kind === "secret" ? TextInput.Password : TextInput.Normal
                                    placeholderText: row.modelData.kind === "secret" && row.modelData.hasValue ? "(set; type to replace)" : ""
                                    placeholderTextColor: Theme.muted
                                    color: Theme.text
                                    font.family: Theme.family
                                    selectByMouse: true
                                    background: Rectangle { radius: 6; color: Theme.surface2; border.width: input.activeFocus ? 2 : 1; border.color: input.activeFocus ? Theme.accent : Theme.border }
                                    onTextEdited: section.edit(row.modelData.name, text)
                                    onTextChanged: if (row.modelData.kind === "path") section.edit(row.modelData.name, text)
                                }
                                Btn {
                                    visible: row.modelData.kind === "path"
                                    text: "Browse…"
                                    onClicked: { page.pathTarget = input; folderDialog.open() }
                                }
                            }
                        }
                        Btn {
                            visible: !section.modelData.instant
                            primary: true
                            text: "Save"
                            Layout.alignment: Qt.AlignRight
                            onClicked: backend.settingsController.save(section.modelData.id, section.collect())
                        }
                    }
                }
            }
        }
    }
}
