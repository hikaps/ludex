import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

Item {
    id: page
    property string pendingKey: ""
    function focusSearch() {
        query.forceActiveFocus()
        query.selectAll()
    }
    onVisibleChanged: if (visible) query.forceActiveFocus()

    FolderDialog {
        id: folderDialog
        title: "Download to"
        onAccepted: backend.installHit(page.pendingKey, backend.localPath(selectedFolder.toString()))
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 14

        Txt { text: "Search"; font.pixelSize: Theme.title; font.bold: true }
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            TextField {
                id: query
                Layout.fillWidth: true
                placeholderText: "Search the stores, then press Enter"
                color: Theme.text
                placeholderTextColor: Theme.muted
                font.family: Theme.family
                font.pixelSize: Theme.body
                selectByMouse: true
                leftPadding: 14
                background: Rectangle {
                    radius: height / 2
                    color: Theme.surface2
                    border.width: query.activeFocus ? 2 : 1
                    border.color: query.activeFocus ? Theme.accent : Theme.border
                }
                onAccepted: backend.search(text)
                Keys.onDownPressed: results.forceActiveFocus()
            }
            Btn { primary: true; text: backend.searching ? "Searching…" : "Search"; enabled: !backend.searching; onClicked: backend.search(query.text) }
        }

        ListView {
            id: results
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: backend.hits
            keyNavigationEnabled: true
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                id: hit
                required property var modelData
                required property int index
                width: results.width - 12
                height: 84
                radius: Theme.radius
                color: ListView.isCurrentItem && results.activeFocus ? Theme.surface3 : Theme.surface
                border.width: 1
                border.color: Theme.border
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 14
                    CoverArt { Layout.preferredWidth: 42; Layout.preferredHeight: 63; title: hit.modelData.title; seed: hit.index + 7 }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Txt { Layout.fillWidth: true; text: hit.modelData.title; font.bold: true; font.pixelSize: 16; elide: Text.ElideRight }
                        Txt { text: hit.modelData.store + (hit.modelData.price !== "" ? "  ·  " + hit.modelData.price : ""); color: Theme.muted; font.pixelSize: Theme.small }
                    }
                    Chip { visible: hit.modelData.owned; text: "You own this"; checked: true; interactive: false }
                    Btn {
                        text: backend.hitNeedsFolder(hit.modelData.key) ? "Download" : "Install"
                        onClicked: {
                            if (backend.hitNeedsFolder(hit.modelData.key)) {
                                page.pendingKey = hit.modelData.key
                                folderDialog.currentFolder = backend.folderUrl(backend.downloadFolder())
                                folderDialog.open()
                            } else {
                                backend.installHit(hit.modelData.key, "")
                            }
                        }
                    }
                }
            }
            Txt {
                anchors.centerIn: parent
                visible: results.count === 0
                color: Theme.muted
                text: backend.searching ? "Searching…" : "Type a title to search every store you have a plugin for."
            }
        }
    }
}
