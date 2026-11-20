import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: page
    onVisibleChanged: if (visible) backend.pollJobs()

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 24
        spacing: 14

        Txt { text: "Jobs"; font.pixelSize: Theme.title; font.bold: true }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: backend.jobs
            ScrollBar.vertical: ScrollBar {}
            delegate: Rectangle {
                id: job
                required property var modelData
                readonly property bool running: modelData.state === "running"
                width: list.width
                height: running ? 92 : 64
                radius: Theme.radius
                color: Theme.surface
                border.width: 1
                border.color: Theme.border
                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    spacing: 6
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 12
                        Txt { Layout.fillWidth: true; text: job.modelData.title; font.bold: true; elide: Text.ElideRight }
                        Chip { text: job.modelData.kind; interactive: false }
                        Chip {
                            text: job.modelData.state
                            interactive: false
                            checked: job.running
                        }
                        Btn { visible: job.running; text: "Stop"; implicitHeight: 30; onClicked: backend.stopJob(job.modelData.id) }
                    }
                    Txt {
                        visible: job.running
                        Layout.fillWidth: true
                        text: job.modelData.progress
                        color: Theme.muted
                        font.pixelSize: Theme.small
                        elide: Text.ElideRight
                    }
                    Rectangle {
                        visible: job.running
                        Layout.fillWidth: true
                        implicitHeight: 4
                        radius: 2
                        color: Theme.surface3
                        clip: true
                        Rectangle {
                            id: slider
                            width: parent.width * 0.3
                            height: parent.height
                            radius: 2
                            color: Theme.accent
                            SequentialAnimation on x {
                                running: job.running && page.visible
                                loops: Animation.Infinite
                                NumberAnimation { from: 0; to: slider.parent.width * 0.7; duration: 900; easing.type: Easing.InOutQuad }
                                NumberAnimation { from: slider.parent.width * 0.7; to: 0; duration: 900; easing.type: Easing.InOutQuad }
                            }
                        }
                    }
                    Txt {
                        visible: !job.running
                        Layout.fillWidth: true
                        text: "started " + job.modelData.started
                        color: Theme.muted
                        font.pixelSize: Theme.small
                    }
                }
            }
            Txt {
                anchors.centerIn: parent
                visible: list.count === 0
                color: Theme.muted
                text: "Nothing is running. Launches, installs and downloads appear here."
            }
        }
    }
}
