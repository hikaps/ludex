import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Pick which database entry a game's title and details come from (or forget the match).
Dialog {
    id: dialog
    objectName: "matchDialog"
    property int gameId: -1
    property string heading: ""

    modal: true
    anchors.centerIn: Overlay.overlay
    width: Math.min(640, Overlay.overlay ? Overlay.overlay.width - 48 : 640)
    padding: 20
    background: Rectangle { radius: Theme.radius; color: Theme.surface2; border.width: 1; border.color: Theme.border }
    header: Txt { text: "Match: " + dialog.heading; font.bold: true; font.pixelSize: 18; padding: 20; bottomPadding: 0; elide: Text.ElideRight; width: dialog.width }

    function openFor(id, title) {
        gameId = id
        heading = title
        backend.clearMatches()
        query.text = backend.matchQuery(id)
        open()
        search()
    }
    function search() {
        backend.findMatches(query.text)
    }
    onClosed: backend.clearMatches()

    contentItem: ColumnLayout {
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            TextField {
                id: query
                Layout.fillWidth: true
                implicitHeight: 36
                color: Theme.text
                font.family: Theme.family
                selectByMouse: true
                background: Rectangle { radius: 6; color: Theme.surface; border.width: query.activeFocus ? 2 : 1; border.color: query.activeFocus ? Theme.accent : Theme.border }
                onAccepted: dialog.search()
            }
            Btn { text: backend.matching ? "Searching…" : "Search"; primary: true; enabled: !backend.matching; onClicked: dialog.search() }
        }
        Txt {
            Layout.fillWidth: true
            color: Theme.muted
            font.pixelSize: Theme.small
            wrapMode: Text.Wrap
            text: "Searching sends the text above to the database plugins. Pick an entry to use its title and details."
        }
        ListView {
            id: list
            objectName: "matchList"
            Layout.fillWidth: true
            Layout.preferredHeight: 260
            clip: true
            spacing: 6
            model: backend.matches
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            delegate: Rectangle {
                required property var modelData
                required property int index
                width: list.width
                height: 48
                radius: 8
                color: hover.hovered ? Theme.surface3 : Theme.surface
                border.width: 1
                border.color: Theme.border
                HoverHandler { id: hover }
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 10
                    Txt { Layout.fillWidth: true; text: modelData.title; elide: Text.ElideRight }
                    Txt { text: modelData.plugin; color: Theme.muted; font.pixelSize: Theme.small }
                }
                TapHandler { onTapped: { backend.chooseMatch(dialog.gameId, index); dialog.close() } }
            }
            Txt {
                anchors.centerIn: parent
                visible: list.count === 0 && !backend.matching
                color: Theme.muted
                text: "No entries found"
            }
        }
    }

    footer: RowLayout {
        spacing: 8
        Btn { text: "Clear match"; Layout.leftMargin: 20; onClicked: { backend.chooseMatch(dialog.gameId, -1); dialog.close() } }
        Item { Layout.fillWidth: true }
        Btn { text: "Cancel"; onClicked: dialog.close() }
        Item { Layout.preferredWidth: 12 }
    }
}
