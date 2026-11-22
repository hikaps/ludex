import QtQuick

// One game in the library grid: cover, title, stores and a Play or Install button on hover.
Item {
    id: card
    required property int index
    required property int gameId
    required property string title
    required property string stores
    required property bool installed
    required property string played
    required property string coverUrl
    property bool current: false
    signal opened()

    readonly property bool lifted: mouse.containsMouse || current

    Component.onCompleted: backend.requestCover(gameId)
    Component.onDestruction: if (backend) backend.cancelCover(gameId)

    Rectangle {
        id: face
        anchors.fill: parent
        anchors.margins: 8
        radius: 4
        color: Theme.surface
        clip: true
        scale: card.lifted ? (consoleMode ? 1.08 : 1.035) : 1
        Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }

        CoverArt {
            id: art
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            height: width * 1.5
            source: card.coverUrl
            title: card.title
            seed: card.gameId
        }
        Rectangle {
            anchors.fill: art
            gradient: Gradient {
                GradientStop { position: 0.55; color: "transparent" }
                GradientStop { position: 1.0; color: "#cc000000" }
            }
        }
        Chip {
            visible: card.installed
            text: "Installed"
            checked: true
            interactive: false
            anchors.top: art.top
            anchors.right: art.right
            anchors.margins: 8
        }
        Btn {
            id: play
            focusPolicy: Qt.NoFocus
            primary: true
            text: card.installed ? "Play" : "Install"
            anchors.horizontalCenter: art.horizontalCenter
            anchors.bottom: art.bottom
            anchors.bottomMargin: 12
            opacity: card.lifted ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: 140 } }
            onClicked: card.installed ? backend.launch(card.gameId) : backend.install(card.gameId)
        }
        Column {
            anchors.top: art.bottom
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 10
            anchors.topMargin: 8
            spacing: 2
            Txt { width: parent.width; text: card.title; font.bold: true; font.pixelSize: consoleMode ? 17 : Theme.body; elide: Text.ElideRight }
            Txt { width: parent.width; text: card.played !== "" && card.played !== "never" ? card.stores + " · " + card.played : card.stores
                  font.pixelSize: consoleMode ? 14 : Theme.small; color: Theme.muted; elide: Text.ElideRight }
        }
        // Drawn as a child so it paints over the cover; a Rectangle's own border sits under its children.
        Rectangle {
            anchors.fill: parent
            z: 10
            color: "transparent"
            radius: parent.radius
            border.width: card.current ? (consoleMode ? 5 : 3) : 0
            border.color: Theme.accent
        }
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        z: -1
        cursorShape: Qt.PointingHandCursor
        onClicked: card.opened()
    }
}
