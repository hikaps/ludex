import QtQuick

Rectangle {
    id: chip
    property alias text: label.text
    property bool checked: false
    property bool interactive: true
    signal clicked()

    implicitWidth: label.implicitWidth + 24
    implicitHeight: 28
    radius: height / 2
    color: checked ? Theme.accent : (mouse.containsMouse && interactive ? Theme.surface3 : Theme.surface2)
    Behavior on color { ColorAnimation { duration: 120 } }

    Txt {
        id: label
        anchors.centerIn: parent
        font.pixelSize: Theme.small
        color: chip.checked ? "#ffffff" : Theme.muted
    }
    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        enabled: chip.interactive
        cursorShape: Qt.PointingHandCursor
        onClicked: chip.clicked()
    }
}
