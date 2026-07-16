## Порядок описания объектов SEAF
Описание объектов необходимо осуществлять в следующей последовательности, сначала создается родительский (parent) объект, затем дочерние (child) ссылающийся на родителя
- Регион - *seaf.ta.services.dc_region*
    - Зона доступности - *seaf.ta.services.dc_az*
        - Офис/ЦОД                           - *seaf.ta.services.office / seaf.ta.services.dc*
            - Зоны безопасности               - *seaf.ta.services.network_segment* (type : см. модель SEAF)
                - Сети                         - *seaf.ta.services.network* (type: 'LAN')
                - Провайдеры услуг связи (ISP) - *seaf.ta.services.network* (type: 'WAN')
                - Сетевые устройства           - *seaf.ta.components.network* (type : см. модель SEAF)
                - Сервисы КБ                   - *seaf.ta.services.kb* (type : см. модель SEAF)
                - Сервисы ТА                   - *seaf.ta.services.compute_service/seaf.ta.services.cluster/etc* (type : см. модель SEAF)
## Описание объектов Draw IO
| ID                           | Описание                                                                          |
|------------------------------|-----------------------------------------------------------------------------------|
| **region**                   | Описание региона (seaf.ta.services.dc_region)                                     |
| **az**                       | Описание зоны доступности (seaf.ta.services.dc_az)                                |
| **office**                   | Описание офиса (seaf.ta.services.office)                                          |
| **dc**                       | Описание ЦОД (seaf.ta.services.dc)                                                |
| **segment_internet**         | Зона доступности Интернет (seaf.ta.services.network_segment)                      |
| **segment_transport_wan**    | Зона доступности WAN (seaf.ta.services.network_segment)                           |
| **isp**                      | Описание провайдера услуг связи (seaf.ta.services.network)                        |
| **office_label**             | Описание офиса (ярлык) на странице диаграммы офиса (seaf.ta.services.office)      |
| **dc_label**                 | Описание ЦОД (ярлык) на странице диаграммы ЦОД (seaf.ta.services.office)          |
| **segment_dmz**              | Описание зоны доступности ДМЗ (seaf.ta.services.network_segment)                  |
| **segment_inet_edge**        | Описание зоны доступности INET-EDGE (seaf.ta.services.network_segment)            |
| **segment_int_wan-edge**     | Описание зоны доступности INT-WAN-EDGE (seaf.ta.services.network_segment)         |
| **segment_int_net**          | Описание зоны доступности INT-NET (seaf.ta.services.network_segment)              |
| **segment_int_security_net** | Описание зоны доступности NT-SECURITY-NET (seaf.ta.services.network_segment)      |
| **segment_ext_wan_edge**     | Описание зоны доступности EXT-WAN-EDGE (seaf.ta.services.network_segment)         |
| **lan**                      | Описание внутренних сетей (seaf.ta.services.network)                              |
| **router**                   | Описание сетевого устройства(seaf.ta.components.network)                          |
| **firewall**                 | Описание сетевого устройства(seaf.ta.components.network)                          |
| **wireless_controller**      | Описание сетевого устройства(seaf.ta.components.network)                          |
| **network_links**            | Описание связей между сетевыми устройствами и сетями (seaf.ta.components.network) |
---------------------------------------------------------------------------------------------------------------------
